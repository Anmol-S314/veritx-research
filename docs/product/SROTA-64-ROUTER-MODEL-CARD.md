# Model card — 64-router SROTA candidate (evidence record)

Status: **artifacts deleted; evidence record only.** Written 2026-11-11 after the execution tree
`~/.cache/veritx-noc-lab/vla-native-execution/experiments/constellation_topology_rtl/` disappeared
from disk. Every number below comes from audit files that survived in this repository, or from
runner receipts quoted in `RTL-FINAL-CLOSEOUT-STATUS.md`. Nothing here is re-derivable from the
repository alone, because the Chisel source (`CatalogRtlSrotaTop.scala`, `SrotaFiuTelemetry.scala`)
lived inside the deleted tree and was never committed.

## What the model is

An emitted constellation SROTA (source-routed) network candidate at bounded small scale. It is
**not** the pinned selected target (`p-fd7e5e31be77-r02`: 74 endpoints, 81 routers, 8 VCs,
162 shared wires, 128-bit flits), and it is not a KNCube, GEC, or ring family.

| Field | Value | Source |
|---|---|---|
| Routers | 64 | `runs/srota-real-cell-pin-audit-20261111.json` |
| Links | 896 | hierarchy assembly record |
| VCs | 4 | hierarchy assembly record |
| Depth | 8 | hierarchy assembly record |
| Flit payload | 128 bit (4 × 32-bit words) | port audit |
| Unique modules | 1,491 | hierarchy assembly record |
| Source files | 194 | hierarchy assembly record |
| Cell pins | 384 per cell, 24,576 total, all name/direction/width matched | `runs/srota-real-cell-pin-audit-20261111.json` |
| Top terminal ports | 898 | Icarus preparation script contract |
| Assembled top SHA-256 | `3fc7d8a3c3e1362062c5cd4925cb730aec65f668a31517fd7450e514cfe61514` | hierarchy assembly record |
| Linked top SHA-256 | `a3f5ab9ffcdea2f15866620748762bc89a1f7d14895c8307dd917a3bba1bbbf9` | integration receipt |
| Simulator SHA-256 | `dd11fce70849394953f40381c8de967ba7a7acd0d29ac2f0185926bdde0e11f3` | `runs/srota-integrated-smoke-audit-20261111.json` |
| Toolchain | Verilator 5.032 (Debian 5.032-1) | cell-lint record |

## Interface

Per endpoint, ingress: `valid`, `head`, `tail`, `route_tag[1:0]`, `payload[127:0]`,
`egress_id[5:0]`. Per endpoint, egress: `valid`, `head`, `tail`, `route_tag[1:0]`,
`ingress_id[5:0]`, `payload[127:0]`. Global: `clock`, `reset`.

## Build method

1. Each of the 64 real router cells compiled separately with Verilator `--cc --lib-create` into a
   static DPI library, under a 4-GiB cgroup cap, one job at a time.
2. Full unmodified top linked against all 64 libraries plus a C++ packet driver.
3. Warning policy: exactly one suppression, `-Wno-UNOPTFLAT`, forced by cross-port dependency
   over-approximation in the six generated DPI combinational update calls per router. No
   `-Wno-fatal`, no WIDTH/PINNOTFOUND/LATCH suppression.
4. Strict partitioned lint: 65/65 (64 cells plus top with ABI boundaries), zero emitted warnings
   under declared unused/style and boundary-only UNDRIVEN waivers.
5. All 384 DPI imports resolved against their matching libraries.

No interface-only ABI stubs, no capacity reduction, no topology substitution.

## Measured behaviour

All-pairs campaign (`runs/srota-allpairs-stimulus-audit-20261111.json`,
`runs/srota-allpairs-traffic-statistics-20261111.json`):

- 4,096 packets, one per ordered endpoint pair; 4,096/4,096 pairs delivered
- 17,408 mixed-length flits (1/2/5/9 flits, 1,024 packets each), all accepted and delivered
- 8,799 held-output stability checks, 2,988 cycles
- 272 packets injected per source and received per destination (perfect balance)
- Packet latency in cycles: min 4, median 153, p95 352, max 487
- Delivered route tags: 13,238 tag-0, 4,170 tag-1
- Stimulus SHA-256 `b1e442749ea325f7e18dd047205ddba15822b75b6da1f85889aa2759a45b83ba`

Single-packet smoke: 1 accepted, 1 delivered, 788 stability checks, 1,032 cycles
(`runs/srota-integrated-smoke-audit-20261111.json`).

Both campaigns used deterministic bounded sink stalls, including a forced contiguous
backpressure window, and were gated by an independent event checker that reconstructs expected
payloads, framing, ordering, route-tag stability, and conservation from the stimulus.

## Qualification status: `qualified: false`

Not covered:

- Reset asserted during live traffic, and recovery/conservation after that reset
- Approved-capture workload replay (the all-pairs and single-packet stimuli are synthetic)
- Transaction-layer (AXI5/CHI/TileLink) behaviour through this fabric
- Native KNCube equivalence to the absent `KNCubeSourceSpec`
- Physical implementation: synthesis, placement, timing, DRC/LVS/GDS
- The selected 81-router / 74-endpoint target

## Reproduction status: blocked

The simulator, the 64 cell libraries, the emitted Verilog, the Chisel source, and the private
runner are all in the deleted execution tree. Reproducing this model card requires, in order:

1. Restore or re-author the constellation Scala source for `CatalogRtlSrotaTop` and its 64 cells.
2. Re-emit cells and re-run the binding/hash audit.
3. Rebuild the 64 DPI cell libraries and relink the top.
4. Re-run the single-packet and all-pairs campaigns plus their independent event audits.

Until then, treat these figures as historical evidence of a run that passed at its stated scope,
not as a currently reproducible result.
