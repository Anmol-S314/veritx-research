# Ramulator2 vendor record (VeriTX memory backend, Phase 15)

- Upstream: https://github.com/CMU-SAFARI/ramulator2
- Pinned commit: `72427a1bba3771564c4fb0e494ba02242fd1eaa7`
  ("generalize RFM command targeting", 2026)
- Vendored: 2026-09-18 (shallow clone; full history NOT kept, per repo
  convention — cf. third_party/astra-sim, which also carries no .git).
- Pruned vs upstream (not needed for the simulation backend):
  - `ext/` (FetchContent deps: fmt, yaml-cpp, nanobind) — re-fetched by
    CMake at build time (build host needs network). Keeps the vendor
    tree at ~2MB instead of ~48MB.
  - `visualizer/` (Nuxt/WebGL trace UI) — unrelated to the backend.
  - `build/`, `*.so`, `__pycache__` — build outputs, never vendored.

## Build

```bash
cd third_party/ramulator2 && ./build.sh        # Python bindings ON (default)
cd third_party/ramulator2 && BUILD_DIR=/tmp/rambuild ./build.sh   # out-of-tree
```

- Requires: CMake, C++17 compiler, Python ≥3.10 dev headers for bindings.
- Bindings compile against the building interpreter: the extension is
  `cpython-3XX`-tagged. VeriTX hosts run 3.14 and the tools image runs
  3.10 — build inside the target interpreter (Phase-15 integration builds
  in-image; see MEMORY-ROADMAP Appendix D).
- `PYTHONPATH=third_party/ramulator2/python python3.12
  third_party/ramulator2/examples/example_config.py` is the smoke test
  (DDR4, expects controller stats on stdout).

## Stage-1 integration boundary (spike-proven 2026-09-18)

`ReadWriteTrace` frontend: text lines `R|W ch,pc,sid,bg,bank,row,col`
(HBM3 = 7-level addr_vec), issues one request per frontend tick, replays
once. Python config: `dram.HBM3(org_preset="HBM3_16Gb_8hi",
timing_preset="HBM3_6400Mbps")` + `controller.HBM34` + FRFCFS + open-row +
`PassThroughAddrMapper` + `NoRefresh`. Row-locality differentiation proven:
4096 reads, 4063 hits/0 conflicts (1 row) vs 0 hits/4063 conflicts (64-row
round-robin), 17.7× completion gap. Caveat: stats sample pre-drain (~32 in
flight at EOF) — Phase-15 conservation must drain-count, not EOF-count.
