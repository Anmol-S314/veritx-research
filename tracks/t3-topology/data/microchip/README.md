# Gen 6-class switch fabric — experiment data

This directory holds the results of the hypothetical Gen 6-class 16-port
switch-fabric experiment. The workload is authored and synthetic; the
cycle-level fabric evaluation is a real BookSim run through the certified
`FabricCompiler` + `FabricEvaluator` path.

- Template: `tracks/t3-topology/examples/switch_gen6_class-v4.json`
- Experiment: `tracks/t3-topology/dse/tools/run_microchip_switch.py`
- Narrative and claim boundary: `docs/product/microchip-experiment.md`
- Research brief: `docs/product/microchip-use-case.md`

## Reproduce

From the repository root:

```sh
PYTHONPATH=tracks/t3-topology/dse \
  python3 tracks/t3-topology/dse/tools/run_microchip_switch.py
```

The script writes `results.json` and `results.md` here. Per-run BookSim
evidence is written under `runs/<UTC timestamp>/<topology>/` (gitignored).
The script exits non-zero and writes a blocker report if BookSim is absent or
unqualified, and records topology refusals instead of skipping them.

## Result summary

BookSim producer: `third_party/booksim2/src/booksim`, producer revision
`f71b10b39892571e9d4ed907fef23e85360c62b6`, `execution_fidelity=QUALIFIED`
on all five runs. Network clock: 1 GHz. Per-topology timeout: 180 s. Mesh,
fat tree, flatfly and SROTA Plane D each injected and accepted 729,760 flits
across 91,244 trace packets. GEC MECS injected and accepted 732,782 flits
across 91,662 trace packets.

| topology | completion cycles | p50 cycles | p95 cycles | p99 cycles | derived accepted flits/cycle |
|---|---:|---:|---:|---:|---:|
| 4x4 mesh | 309,129 | 32,221 | 64,496 | 67,147 | 2.360697 |
| fat tree (radix 4, 2 tiers) | 567,480 | 38,351 | 72,147 | 75,135 | 1.285966 |
| flatfly (radix 4 x 2 dims) | 219,232 | 20,062 | 38,249 | 40,714 | 3.328711 |
| SROTA Plane D (4x4, concentration 1) | 382,993 | 34,433 | 68,263 | 74,433 | 1.905413 |
| GEC MECS (4x4) | 242,234 | 21,719 | 52,835 | 58,994 | 3.025100 |

SROTA uses Plane D only; the prior Plane C + D + T variant was refused by the
multiclass BookSim projection due to shared VC subsets. This experiment makes
no claim about SROTA control or telemetry planes. Its profile is
`CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1`. GEC MECS uses profile
`CERTIFIED_BOOKSIM_GEC_MECS_V1`. Accepted-flit rates are derived from reported
counters and completion cycles, not native BookSim throughput metrics.

The accepted-flit rate is arithmetic on reported counters, not a BookSim
metric. This BookSim build emitted an empty `hops` map and no native
`throughput` key; both are left absent, not zero-filled.

## Workload shape

16 port-proxy ranks: hosts 0–7, SSD port proxies 8–15. 170 unicast profiles
in six classes. The base read/write mix is exactly 70/30 by declared payload
bytes (14,909,440 read / 6,389,760 write), using 4 KiB and 256 KiB classes.
Two additional overlay classes are an incast pair to SSD port 0 (rank 8) and
a multicast-equivalent duplicate-unicast fan-out to all eight SSD ports.
The schema has no true multicast primitive.

## Caveats

- This is not Switchtec, not a PCIe protocol model, and not a measurement of
  any Microchip product.
- The host/SSD port model, traffic mix, payload classes, incast and fan-out
  are synthetic. No real system trace was used.
- Profiles encode the host→SSD issue direction; read data-return direction is
  not separately modeled.
- Per-class latency rows are reported as printed. Their `pkt_count` values do
  not reconcile with class flit volume or the aggregate trace-request count,
  so class-level percentiles are diagnostics, not validated class-isolation
  measurements.
- No partition isolation, buffer-depth, VC-count, multicast-replication-point
  or absolute PPA claim is supported by this data.

See `docs/product/microchip-experiment.md` for the full do-not-claim list.
