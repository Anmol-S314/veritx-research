# Hypothetical Gen 6-class switch fabric: what the BookSim experiment shows

Status: experiment report for an **authored hypothetical** 16-port switch
fabric. It is design-space exploration, not a model of a shipping Microchip
product. The research brief is `docs/product/microchip-use-case.md`.

## Bottom line

A real cycle-level BookSim evaluation ran on five 16-endpoint topologies
using the repository's compiler/evaluator path. All five compiled and all five
evaluated with qualified BookSim. The workload and port model are synthetic.
Within this workload:

- the 4x4 mesh completed in 309,129 cycles with p99 67,147 cycles;
- the radix-4, two-tier fat tree completed in 567,480 cycles with p99 75,135
  cycles;
- the radix-4 x 2-dimension flatfly completed in 219,232 cycles with p99
  40,714 cycles.
- GEC MECS completed in 242,234 cycles with p99 58,994 cycles.
- SROTA Plane D completed in 382,993 cycles with p99 74,433 cycles.

Those are observations for one authored traffic matrix, not a topology
ranking. The evaluated fabrics are not iso-area or iso-power, and the fat-tree
execution uses the generic AnyNet profile rather than a fat-tree-specific
route. SROTA is configured with Plane D only; this result does not evaluate
its control or telemetry planes.

## What ran

From the repository root:

```sh
PYTHONPATH=tracks/t3-topology/dse \
  python3 tracks/t3-topology/dse/tools/run_microchip_switch.py
```

Artifacts:

- `tracks/t3-topology/examples/switch_gen6_class-v4.json` — the v4 template
  (4x4 mesh, 16 port-proxy ranks, 256-bit links, 1 GHz, 4 nm metadata).
- `tracks/t3-topology/workloads/registry.json` — entry
  `switch-gen6-class` / "Gen 6-class switch fabric · hypothetical".
- `tracks/t3-topology/dse/tools/run_microchip_switch.py` — experiment
  runner.
- `tracks/t3-topology/data/microchip/results.json` and `results.md` — this
  run's metrics, evidence digests and caveats.
- `tracks/t3-topology/data/microchip/README.md` — data-directory guide.

BookSim producer: `third_party/booksim2/src/booksim`, producer revision
`f71b10b39892571e9d4ed907fef23e85360c62b6`, build recipe
`booksim2-fork/v2`. All five runs reported `execution_fidelity=QUALIFIED`
and `producer_dirty=false`. The network clock is an explicit 1 GHz modeling
assumption; per-topology timeout was 180 s. Mesh, fat tree, flatfly and SROTA
each loaded 91,244 trace packets and injected/accepted 729,760 flits. GEC MECS
loaded 91,662 trace packets and injected/accepted 732,782 flits.

## The fabric and the workload

The template is a **16-port proxy** model, not the 20-port, 160-lane
Switchtec part from the brief. Sixteen `compute_tile` agents represent fabric
ports: ranks 0–7 are host port proxies, ranks 8–15 are SSD port proxies.
There is no HBM agent.

The synthetic workload has 170 unicast profiles in six classes:

| class | profiles | declared bytes | intent |
|---|---:|---:|---|
| `read_256k` | 56 | 14,680,064 | host→SSD reads, 256 KiB |
| `read_4k` | 56 | 229,376 | host→SSD reads, 4 KiB |
| `write_256k` | 24 | 6,291,456 | host→SSD writes, 256 KiB |
| `write_4k` | 24 | 98,304 | host→SSD writes, 4 KiB |
| `incast_ssd0` | 2 | 524,288 | hosts 0 and 1 both target SSD port 0 (rank 8), 256 KiB each |
| `multicast_equiv` | 8 | 524,288 | host 0 duplicate-unicast fan-out to all eight SSD ports, 64 KiB each |

The base read/write mix is exactly 70/30 by declared payload bytes
(14,909,440 / 6,389,760). The incast and multicast-equivalent classes are
additional overlays, not part of the 70/30 base. Profiles encode the
host→SSD issue direction only; read data-return direction is not separately
modeled. The schema has no true multicast primitive, so the fan-out is
duplicate unicast: no source/spine/destination replication point is modeled.

## Topology results

All five runs use the same workload, 256-bit links, 1 GHz network clock,
and 16 attached endpoints. SROTA is Plane D only, 4x4 with concentration 1; GEC MECS is a
4x4 grid with concentration 1, one shared channel group per dimension and
three destinations per express channel. The mesh is 16 routers with one
endpoint each; the fat tree is 8 radix-4 switches; the flatfly is 16 routers
with one endpoint each.

| topology | BookSim profile | compile | completion cycles | p50 cycles | p95 cycles | p99 cycles | flits accepted |
|---|---|---|---:|---:|---:|---:|---:|
| 4x4 mesh | `CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1` | PASS | 309,129 | 32,221 | 64,496 | 67,147 | 729,760 |
| fat tree, radix 4, 2 tiers | `CERTIFIED_BOOKSIM_ANYNET_MC_V1` | PASS | 567,480 | 38,351 | 72,147 | 75,135 | 729,760 |
| flatfly, radix 4 x 2 dims | `CERTIFIED_BOOKSIM_FLATFLY_MIN_V1` | PASS | 219,232 | 20,062 | 38,249 | 40,714 | 729,760 |
| SROTA Plane D, 4x4 concentration 1 | `CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1` | PASS | 382,993 | 34,433 | 68,263 | 74,433 | 729,760 |
| GEC MECS, 4x4 | `CERTIFIED_BOOKSIM_GEC_MECS_V1` | PASS | 242,234 | 21,719 | 52,835 | 58,994 | 732,782 |

Supporting counters and derived rates:

| topology | sample window | packet latency avg | flit latency avg | loaded packets | derived accepted flits/cycle | derived loaded packets/cycle |
|---|---:|---:|---:|---:|---:|---:|
| mesh | 309,132 | 32,693.5 | 61.8039 | 91,244 | 2.360697 | 0.295165 |
| fattree | 567,483 | 38,312.9 | 55.8526 | 91,244 | 1.285966 | 0.160788 |
| flatfly | 219,235 | 19,648.5 | 31.8500 | 91,244 | 3.328711 | 0.416198 |
| SROTA Plane D | 382,996 | 34,803.3 | 15.6089 | 91,244 | 1.905413 | 0.238239 |
| GEC MECS | 242,237 | 23,068.0 | 70.7707 | 91,662 | 3.025100 | 0.378403 |

The SROTA run uses the `planes={"d"}` intent; the earlier `{"c", "d", "t"}`
variant was refused because the multiclass BookSim projection found shared
VC subsets. This experiment therefore makes no claim about Plane C or Plane T.
GEC MECS reports 732,782 accepted flits, so its derived rate is 3.025100
flits/cycle (not native BookSim throughput).

`completion_cycles` and the percentiles come from the authenticated BookSim
evidence. The two rate columns are arithmetic on reported counters
(`flits_accepted / completion_cycles` and `loaded_trace_packets /
completion_cycles`), not BookSim-reported metrics.

### What was not emitted

This BookSim build returned an empty `hops` map and no native `throughput`
key. Both are left absent in `results.json`; they are not zero-filled. The
aggregate `pkt_count` is 2,140 for mesh and flatfly and 1,106 for fat tree:
those are the trace-request latency samples the percentiles were computed
over, not the 91,244 packets loaded.

### Class-scoped rows (diagnostics)

Flit counters are consistent across topologies; p99 rows are reported as the
build printed them.

| class | flits injected | mesh p99 | fattree p99 | flatfly p99 |
|---|---:|---:|---:|---:|
| `incast_ssd0` | 17,120 | 67,147 | 75,135 | 40,714 |
| `multicast_equiv` | 17,120 | 72,840 | 73,687 | 71,144 |
| `read_256k` | 479,360 | 147,620 | 146,406 | 146,706 |
| `read_4k` | 7,504 | 6,440 | 15,954 | 4,456 |
| `write_256k` | 205,440 | 129,813 | 141,500 | 97,567 |
| `write_4k` | 3,216 | 2,841 | 8,064 | 2,033 |

The per-class flit counters sum to the 729,760 aggregate. The per-class
latency `pkt_count` values do not reconcile with class flit volume or with
the 91,244 loaded packets, so these class-level percentiles are **diagnostic
only**. Do not use them to claim class isolation, per-class QoS, or
multicast latency.

## What is real vs synthetic

**Real.**

- `FabricCompiler` compiled each topology and its certificate passed.
- `FabricEvaluator` ran the pinned BookSim producer through the same
  authenticated path used by
  `tests/test_fabric_evaluator_multiclass_requirements.py`.
- Completion cycles, packet/flit latency, flit counters and per-class
  counters in `results.json` are digest-bound BookSim evidence from that run.
- The producer reported `execution_fidelity=QUALIFIED` on all five runs.

**Synthetic.**

- The host/SSD port model. The 16 `compute_tile` agents are port proxies,
  not CPUs, SSDs, HBM, or a real switch pipeline.
- The 70/30 read/write mix, 4 KiB/256 KiB payload split, incast pair and
  multicast-equivalent fan-out. No Micron, Switchtec or application trace
  was used.
- The topology choices and the 4 nm process value. Process node is metadata;
  nothing in this experiment computes area, power, or timing.
- The host→SSD issue direction only; returns are not separately replayed.

**Not measured.**

- There is no calibration point against a Switchtec Gen 5/6 eval board or
  ChipLink diagnostics, so this is a simulation of a hypothetical fabric, not
  a calibrated digital twin.
- There is no partition-isolation experiment. No partition is pinned at
  100% while a neighbour's p99 is measured.
- There is no buffer-depth, VC-count, arbitration, or multicast
  replication-point sweep.

## Do not claim

- PCIe TLP ordering, config space, credit correctness, FLIT encoding,
  compliance, or Gen 6 electricals. This models a fabric, not a PCIe stack.
- Switchtec internals or any shipping Microchip product. The internal
  topology of the real part is not public.
- Partition isolation or QoS isolation. No such experiment ran.
- Absolute 3 nm/4 nm PPA, area, power, or a Pareto frontier. The 4 nm value
  is a template label only.
- Retimer/SerDes latency. That number is analog, not fabric.
- Ethernet/TSN/EtherCAT conformance or wire-level determinism.
- FPGA place-and-route, timing closure, LUT/BRAM cost, or bitstream
  behaviour.
- Functional safety (ISO 26262/IEC 61508) or security (secure boot, root of
  trust).
- UCIe/BoW/chiplet products at Microchip; there is no public Microchip
  UCIe/die-to-die product.
- CXL protocol semantics.
- Any implication that a Microchip number was measured by us.
- A general topology ranking. These fabrics are not iso-area,
  iso-power, or iso-buffer, and the fat-tree path is a generic AnyNet
  projection rather than a fat-tree-specific certified route.

## Reproduce and inspect

```sh
cd tracks/t3-topology/dse
PYTHONPATH=. pytest -q tests/test_microchip_switch.py tests/test_workload_registry.py
cd ../../..
PYTHONPATH=tracks/t3-topology/dse \
  python3 tracks/t3-topology/dse/tools/run_microchip_switch.py
```

The runner writes `results.json` and `results.md` under
`tracks/t3-topology/data/microchip/`. Per-run evidence goes to
`tracks/t3-topology/data/microchip/runs/<UTC timestamp>/<topology>/`, which
is gitignored. A missing or unqualified BookSim producer produces a blocker
report and a non-zero exit, with no fabricated metrics.
