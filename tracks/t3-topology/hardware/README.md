# T3 — Tenstorrent NoC hardware experiments

**Status: first experiment drafted, NOT yet run on silicon.** The `.cpp` here is
grounded in the real tt-metal API (host: `MeshDevice`/`EnqueueMeshWorkload`; kernel:
`noc_async_write_multicast` + `get_noc_multicast_addr`, verified against tt-metal `main`
examples) but has **not been compiled** — it is a starting point to iterate against the
SDK on a live board. Spots needing on-card verification are tagged `// VERIFY:` in source
and listed in the punch-list below.

This is the first on-hardware code in the repo. Everything else in the track is
modeling/sim; this closes the loop the whole T3 line has been pointing at — measuring the
real programmable Tenstorrent NoC instead of arguing about it.

---

## The experiment: is NoC multicast actually ~flat in fanout?

`interchip_roofline.py` and `multicast_savings.py` assume a multicast delivers a buffer to
`N` cores by crossing the bottleneck **once** — so **wall-time per multicast is ~flat in N**,
and delivered bandwidth (`N × size / time`) grows ~linearly. That assumption is the entire
basis for "multicast beats re-fetching KV/weights." **We have never checked it on real
silicon.** BookSim can't even simulate multicast. Tenstorrent's NoC does it natively.

`noc_multicast_bw.cpp` measures it directly: one sender core reads a payload into L1, then
`noc_async_write_multicast`s it to a rectangle of `N` destination cores, `REPEAT` times.
Sweep `N` (fanout) and payload size; read the shape:

- **wall-time-per-multicast flat in N** → the roofline assumption holds; multicast is a real
  bandwidth lever on this NoC.
- **wall-time grows ~linearly in N** → multicast degenerates toward serial unicast here, and
  the "multicast is ~free" premise fails on real hardware. Either outcome is a real result.

## Run it (Koyeb Wormhole n300)

```bash
# 1. Rent a card:  Koyeb -> TT-N300S instance (single n300).  4x mesh = TT-Loudbox.
# 2. Install the SDK (once):
git clone https://github.com/tenstorrent/tt-metal.git --recurse-submodules
cd tt-metal && ./build_metal.sh            # sets up TT_METAL_HOME + libtt_metal
export TT_METAL_HOME=$PWD
# 3. Build + run this microbench (from the repo root, on the card):
make -C tracks/t3-topology hw              # -> hardware/build.sh
# or directly:
cd tracks/t3-topology/hardware && ./build.sh && ./noc_multicast_bw
```

`make hw` is **deliberately not** wired into `setup`/`lint`/`test`, so the hardware-less CI
matrix never touches it (guarded by `$(call want,...)` — no-ops without the SDK).

## Build integration

Simplest path (documented, avoids reinventing tt-metal's cmake): drop `noc_multicast_bw.cpp`
+ `kernels/` into a clone's `tt_metal/programming_examples/` and build with tt-metal's own
flow. `build.sh` does this via `$TT_METAL_HOME` — see its header. Standalone linking against
`libtt_metal` also works but is more setup; not worth it for one microbench.

## On-card punch-list (the `// VERIFY:` tags)

1. **L1 scratch reservation** — destinations need the multicast target L1 offset reserved
   (a `CircularBuffer` on the full core range) so the write isn't clobbered. Confirm the CB
   config + that sender and dest use the same L1 offset.
2. **Sender self-exclusion** — `noc_async_write_multicast` excludes the sender by default;
   if the sender core sits inside the destination rectangle, use the `_loopback_src` variant
   or shift the rectangle. Confirm `num_dests` = cores actually written.
3. **Timing** — host-side `chrono` around `Finish` includes dispatch latency; `REPEAT` large
   amortizes it. Cross-check one point with the tt-metal device profiler (Tracy) before
   trusting absolute GB/s. The *shape vs N* is robust to this; the absolute number isn't.
4. **num_dests semantics / grid coords** — confirm logical-vs-physical (NoC) core coords for
   `get_noc_multicast_addr` (Wormhole worker grid), and that `num_dests` matches the range.
