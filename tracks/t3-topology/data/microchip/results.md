# Gen 6-class 16-port switch fabric experiment

Status: **COMPLETED**  
Generated: `2026-11-04T21:56:49+00:00`  
Command: `PYTHONPATH=tracks/t3-topology/dse python3 tracks/t3-topology/dse/tools/run_microchip_switch.py`

This is an AUTHORED hypothetical fabric. It is not Switchtec, not a PCIe protocol model, and no Microchip number was measured by us.

## What ran

- Template: `tracks/t3-topology/examples/switch_gen6_class-v4.json`
- Ranks: 16 (hosts 0-7, SSDs 8-15)
- BookSim binary: `third_party/booksim2/src/booksim`
- Network clock: 1,000,000,000 Hz; per-topology timeout: 180 s
- Local run evidence root: `tracks/t3-topology/data/microchip/runs/20261104T215649129694Z` (gitignored; not part of the committed result)

## Workload (synthetic)

170 unicast traffic profiles across 6 classes. Base read/write mix: 70.0% read / 30.0% write by declared payload bytes (14,909,440 / 6,389,760 B).

| class | profiles | declared payload bytes |
|---|---|---|
| `incast_ssd0` | 2 | 524,288 |
| `multicast_equiv` | 8 | 524,288 |
| `read_256k` | 56 | 14,680,064 |
| `read_4k` | 56 | 229,376 |
| `write_256k` | 24 | 6,291,456 |
| `write_4k` | 24 | 98,304 |

70/30 is exact for the read_* / write_* base classes by declared payload bytes; the incast and multicast-equivalent overlay classes are additional.

## Topology results

| topology | compile | eval | BookSim profile | completion cycles | p50 cycles | p95 cycles | p99 cycles | flits accepted | derived accepted flit/cycle |
|---|---|---|---|---|---|---|---|---|---|
| mesh | COMPILED | EVALUATED | CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1 | 309,129 | 32,221.000 | 64,496.000 | 67,147.000 | 729,760 | 2.360697 |
| fattree | COMPILED | EVALUATED | CERTIFIED_BOOKSIM_ANYNET_MC_V1 | 567,480 | 38,351.000 | 72,147.000 | 75,135.000 | 729,760 | 1.285966 |
| flatfly | COMPILED | EVALUATED | CERTIFIED_BOOKSIM_FLATFLY_MIN_V1 | 219,232 | 20,062.000 | 38,249.000 | 40,714.000 | 729,760 | 3.328711 |
| srota | COMPILED | EVALUATED | CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1 | 382,993 | 34,433.000 | 68,263.000 | 74,433.000 | 729,760 | 1.905413 |
| gec_mecs | COMPILED | EVALUATED | CERTIFIED_BOOKSIM_GEC_MECS_V1 | 242,234 | 21,719.000 | 52,835.000 | 58,994.000 | 732,782 | 3.025100 |

### mesh — 4x4 mesh

BookSim profile: `CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1`; design hash `a2147d092385e258…`.

Producer execution fidelity: `QUALIFIED` (producer revision `f71b10b39892`).

Completion window: 309,129 cycles. Trace-request percentiles: p50 32,221.000, p95 64,496.000, p99 67,147.000 cycles. Flits accepted: 729,760 of 729,760 injected.

- `hops`: NOT EMITTED: the authenticated BookSim stats carried an empty hops map; no mean-hop value is claimed.
- `throughput`: NOT EMITTED: BookSim printed no native throughput key; no accepted-rate metric is claimed. See derived counters below.

Derived (not a BookSim-reported metric): 2.360697 accepted flits/cycle, 0.295165 loaded packets/cycle.

| class | flits injected | flits accepted | bytes accepted | p50 cycles | p95 cycles | p99 cycles | pkt_count |
|---|---|---|---|---|---|---|---|
| `incast_ssd0` | 17,120 | 17,120 | 547,840 | 32,221.000 | 64,496.000 | 67,147.000 | 2,140 |
| `multicast_equiv` | 17,120 | 17,120 | 547,840 | 35,843.000 | 69,448.000 | 72,840.000 | 1,203 |
| `read_256k` | 479,360 | 479,360 | 15,339,520 | 38,786.000 | 121,581.000 | 147,620.000 | 25,582 |
| `read_4k` | 7,504 | 7,504 | 240,128 | 2,093.000 | 4,883.000 | 6,440.000 | 952 |
| `write_256k` | 205,440 | 205,440 | 6,574,080 | 42,233.000 | 112,398.000 | 129,813.000 | 20,613 |
| `write_4k` | 3,216 | 3,216 | 102,912 | 1,053.000 | 2,203.000 | 2,841.000 | 408 |

### fattree — fat tree (switch radix 4, 2 tiers)

BookSim profile: `CERTIFIED_BOOKSIM_ANYNET_MC_V1`; design hash `81e2c88195ef0a17…`.

Producer execution fidelity: `QUALIFIED` (producer revision `f71b10b39892`).

Completion window: 567,480 cycles. Trace-request percentiles: p50 38,351.000, p95 72,147.000, p99 75,135.000 cycles. Flits accepted: 729,760 of 729,760 injected.

- `hops`: NOT EMITTED: the authenticated BookSim stats carried an empty hops map; no mean-hop value is claimed.
- `throughput`: NOT EMITTED: BookSim printed no native throughput key; no accepted-rate metric is claimed. See derived counters below.

Derived (not a BookSim-reported metric): 1.285966 accepted flits/cycle, 0.160788 loaded packets/cycle.

| class | flits injected | flits accepted | bytes accepted | p50 cycles | p95 cycles | p99 cycles | pkt_count |
|---|---|---|---|---|---|---|---|
| `incast_ssd0` | 17,120 | 17,120 | 547,840 | 38,351.000 | 72,147.000 | 75,135.000 | 1,106 |
| `multicast_equiv` | 17,120 | 17,120 | 547,840 | 37,594.000 | 70,666.000 | 73,687.000 | 463 |
| `read_256k` | 479,360 | 479,360 | 15,339,520 | 43,297.000 | 125,640.000 | 146,406.000 | 13,632 |
| `read_4k` | 7,504 | 7,504 | 240,128 | 3,351.000 | 14,371.000 | 15,954.000 | 952 |
| `write_256k` | 205,440 | 205,440 | 6,574,080 | 52,128.000 | 122,248.000 | 141,500.000 | 10,561 |
| `write_4k` | 3,216 | 3,216 | 102,912 | 2,820.000 | 7,425.000 | 8,064.000 | 408 |

### flatfly — flatfly (radix 4 x 2 dimensions, concentration 1)

BookSim profile: `CERTIFIED_BOOKSIM_FLATFLY_MIN_V1`; design hash `76c1d0b163115726…`.

Producer execution fidelity: `QUALIFIED` (producer revision `f71b10b39892`).

Completion window: 219,232 cycles. Trace-request percentiles: p50 20,062.000, p95 38,249.000, p99 40,714.000 cycles. Flits accepted: 729,760 of 729,760 injected.

- `hops`: NOT EMITTED: the authenticated BookSim stats carried an empty hops map; no mean-hop value is claimed.
- `throughput`: NOT EMITTED: BookSim printed no native throughput key; no accepted-rate metric is claimed. See derived counters below.

Derived (not a BookSim-reported metric): 3.328711 accepted flits/cycle, 0.416198 loaded packets/cycle.

| class | flits injected | flits accepted | bytes accepted | p50 cycles | p95 cycles | p99 cycles | pkt_count |
|---|---|---|---|---|---|---|---|
| `incast_ssd0` | 17,120 | 17,120 | 547,840 | 20,062.000 | 38,249.000 | 40,714.000 | 2,140 |
| `multicast_equiv` | 17,120 | 17,120 | 547,840 | 40,675.000 | 67,714.000 | 71,144.000 | 2,144 |
| `read_256k` | 479,360 | 479,360 | 15,339,520 | 56,752.000 | 132,904.000 | 146,706.000 | 38,619 |
| `read_4k` | 7,504 | 7,504 | 240,128 | 1,870.000 | 4,026.000 | 4,456.000 | 952 |
| `write_256k` | 205,440 | 205,440 | 6,574,080 | 46,964.000 | 88,059.000 | 97,567.000 | 25,418 |
| `write_4k` | 3,216 | 3,216 | 102,912 | 979.000 | 1,879.000 | 2,033.000 | 408 |

### srota — SROTA Plane D (4x4, concentration 1)

BookSim profile: `CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1`; design hash `814b7b0881653e5f…`.

Producer execution fidelity: `QUALIFIED` (producer revision `f71b10b39892`).

Completion window: 382,993 cycles. Trace-request percentiles: p50 34,433.000, p95 68,263.000, p99 74,433.000 cycles. Flits accepted: 729,760 of 729,760 injected.

- `hops`: NOT EMITTED: the authenticated BookSim stats carried an empty hops map; no mean-hop value is claimed.
- `throughput`: NOT EMITTED: BookSim printed no native throughput key; no accepted-rate metric is claimed. See derived counters below.

Derived (not a BookSim-reported metric): 1.905413 accepted flits/cycle, 0.238239 loaded packets/cycle.

| class | flits injected | flits accepted | bytes accepted | p50 cycles | p95 cycles | p99 cycles | pkt_count |
|---|---|---|---|---|---|---|---|
| `incast_ssd0` | 17,120 | 17,120 | 547,840 | 34,433.000 | 68,263.000 | 74,433.000 | 2,114 |
| `multicast_equiv` | 17,120 | 17,120 | 547,840 | 33,168.000 | 70,254.000 | 73,212.000 | 998 |
| `read_256k` | 479,360 | 479,360 | 15,339,520 | 54,467.000 | 128,211.000 | 148,567.000 | 20,082 |
| `read_4k` | 7,504 | 7,504 | 240,128 | 2,538.000 | 5,734.000 | 6,254.000 | 952 |
| `write_256k` | 205,440 | 205,440 | 6,574,080 | 54,665.000 | 123,489.000 | 142,181.000 | 17,411 |
| `write_4k` | 3,216 | 3,216 | 102,912 | 1,734.000 | 3,271.000 | 3,446.000 | 408 |

### gec_mecs — GEC MECS (4x4, one shared channel group per dimension)

BookSim profile: `CERTIFIED_BOOKSIM_GEC_MECS_V1`; design hash `84f783a677b99de0…`.

Producer execution fidelity: `QUALIFIED` (producer revision `f71b10b39892`).

Completion window: 242,234 cycles. Trace-request percentiles: p50 21,719.000, p95 52,835.000, p99 58,994.000 cycles. Flits accepted: 732,782 of 732,782 injected.

- `hops`: NOT EMITTED: the authenticated BookSim stats carried an empty hops map; no mean-hop value is claimed.
- `throughput`: NOT EMITTED: BookSim printed no native throughput key; no accepted-rate metric is claimed. See derived counters below.

Derived (not a BookSim-reported metric): 3.025100 accepted flits/cycle, 0.378403 loaded packets/cycle.

| class | flits injected | flits accepted | bytes accepted | p50 cycles | p95 cycles | p99 cycles | pkt_count |
|---|---|---|---|---|---|---|---|
| `incast_ssd0` | 17,190 | 17,190 | 550,080 | 21,719.000 | 52,835.000 | 58,994.000 | 2,150 |
| `multicast_equiv` | 17,192 | 17,192 | 550,144 | 33,278.000 | 58,529.000 | 60,162.000 | 2,152 |
| `read_256k` | 481,320 | 481,320 | 15,402,240 | 55,632.000 | 134,766.000 | 146,553.000 | 38,940 |
| `read_4k` | 7,560 | 7,560 | 241,920 | 1,616.000 | 3,323.000 | 3,887.000 | 952 |
| `write_256k` | 206,280 | 206,280 | 6,600,960 | 44,422.000 | 94,131.000 | 109,968.000 | 25,102 |
| `write_4k` | 3,240 | 3,240 | 103,680 | 940.000 | 1,655.000 | 1,993.000 | 408 |

## Caveats

- The workload is synthetic: it is not a Micron or Switchtec trace and no Microchip number was measured by us.
- Profiles encode the host->SSD issue direction; read data-return direction is not separately modeled.
- The schema has no true multicast primitive; the 'multicast_equiv' class is duplicate unicast.
- Per-class latency rows are reported exactly as the BookSim build printed them. Their pkt_count values do not reconcile with class flit volume or the aggregate trace-request count, so class-level percentiles are diagnostics, not validated class-isolation measurements.
- Hops and native throughput were not emitted by this backend run; they are left absent, not zero-filled.
- The 70/30 split is a declared byte mix, not a measured application mix. Only the host->SSD issue direction is replayed.

## What is real vs synthetic

- **Real:** the compiler resolved each 16-endpoint topology and the authenticated BookSim path executed a cycle-level packet/flit simulation. Completion cycles, packet percentiles and flit counters above come from that run's digest-bound evidence.
- **Synthetic:** the host/SSD port model, the 70/30 read/write mix, payload classes, incast pair and multicast-equivalent duplicate-unicast fan-out. No trace from a real system was used.
- **Derived:** accepted flits/cycle and loaded packets/cycle are simple arithmetic on reported counters, labelled as such. Hops and native throughput are absent because this run did not emit them.

## Do not claim

- PCIe TLP ordering, config space, credit correctness, FLIT encoding, compliance, or Gen 6 electricals.
- Switchtec internals or any shipping Microchip product.
- Retimer/SerDes latency.
- Partition isolation; no partition or QoS-isolation experiment ran.
- Buffer-depth, VC-count, or multicast-replication-point sweeps.
- Absolute 3 nm/4 nm PPA, area, or power.
- Functional safety or security.
- CXL or UCIe semantics.

