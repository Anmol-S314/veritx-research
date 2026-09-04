# Changelog

See the [Releases page](https://github.com/Anmol-S314/veritx-research/releases) for versioned changelogs.

## Unreleased

### Added
- **Vendored BookSim2** in `third_party/booksim2/src/` (source from sowmith's
  internal branch `updated-booksim`): GEC express topology (`networks/gec.{cpp,hpp}`),
  matrix traffic pattern, trace-replay trafficmanager, `veritx_ext` extension
  registry, yx routing. Multicast-dependent snakeroute excluded (needs flit mcast).
- **Vendored tool manager** (`scripts/tools.py`, `make tools`, `make tool-*`):
  auto-discovers third-party tools from `METADATA.json`; build with binary
  verification, dependency checks, run, clean, git-tag versioning with
  auto-generated changelogs, interactive version picker.

### Known gap (handoff to sowmith)
- GEC wire-length pricing not yet ported: this gec.cpp refuses
  `use_noc_latency=1` (honest guard) instead of pricing express channels at
  Manhattan pitch. Priced variant lives on branch `alice-booksim-wirepriced`.
  Surfaced by `make tool-info TOOL=booksim2`.
