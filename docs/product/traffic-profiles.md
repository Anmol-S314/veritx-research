# Traffic profiles and raw-trace replay

This is the first front-end slice: describe per-initiator demand, generate a
BookSim trace, or replay an imported trace on a compiled fabric. It does not
model a memory target or cache coherence yet.

## Two paths, two scopes

| Path | Input | Fabric scope | What it preserves |
|---|---|---|---|
| `veritx trace profile` | `veritx/traffic-profile/1` JSON | any BookSim trace consumer | rate, burst, outstanding (latency-bound), read/write mix, payload, target set |
| `veritx evaluate trace` | 5-column BookSim trace | certified standalone profile: connected ANYNET / `ANYNET_MIN_HOPS` fabrics | exact timestamps, packet sizes, endpoint IDs |
| canonical `traffic_profiles` | V4 workload rows | typed fabrics and the catalog path | per-initiator volume, class, destination; dense timestamps |

The raw-trace seam is intentionally narrow. The certified standalone profile
realizes `ANYNET_MIN_HOPS`; a typed mesh compiles to `DOR_XY` and is refused
with a typed reason rather than silently re-routed. The canonical P2P profile
path is being added for typed mesh/torus/etc. and the catalog.

## Generate a trace

```bash
veritx trace profile \
  --spec tracks/t3-topology/examples/traffic/soc-mixed-profile.json \
  --out /tmp/soc-mixed.trace
```

The shipped example describes four initiators (two CPU clusters, a DMA, a GPU)
against HBM endpoints. It is single-class and uses 128-bit flits to match a
128-bit link width.

## One endpoint-level contract

`workload/traffic_source.py` gives the front ends one packet view without
rewriting the simulators:

- `Packet(timestamp, src, dst, traffic_class, flits)`
- `TrafficSourceInfo(identity, addressing, limitations, class_names)`
- `TrafficSource.packets()`, `.to_trace()`, `.scan()`
- `RawTraceSource` — strict 5-column raw trace, single class, endpoint-addressed.
- `RenderedTraceSource` — a rendered canonical trace with dense class indices.
- `CanonicalTraceSource.from_physical_traffic()` — wraps `render_trace` and
  `trace_class_map`.

The contract is honest about its limits: raw is single-class; canonical
timestamps are dense `0..N-1`; a `RANK` source needs an explicit
participant→endpoint mapping before its ids can be compared with an endpoint
trace. It is a seam, not a new simulator.

## Canonical P2P profiles (v4-only)

A V4 workload may carry explicit initiator→target rows:

```json
"workload": {
  "model_family": "custom",
  "tp": 1,
  "traffic_profiles": [
    {"src_rank": 0, "dst_rank": 64, "traffic_class": "soc_mixed", "payload_bytes": 32000},
    {"src_rank": 4, "dst_rank": 66, "traffic_class": "soc_mixed", "payload_bytes": 32000},
    {"src_rank": 32, "dst_rank": 64, "traffic_class": "soc_mixed", "payload_bytes": 128000},
    {"src_rank": 16, "dst_rank": 64, "traffic_class": "soc_mixed", "payload_bytes": 128000}
  ]
}
```

Each row lowers to exactly one `KIND_P2P` `TRANSFER` operation, chained in
declaration order. The rows join the existing class/VC/requirement registry,
so they work on typed mesh/torus/etc. and through the catalog path. This is a
volume/mix layer: it has no per-message timestamps, start cycles, rate, burst,
or outstanding schedule. Timing still comes from the existing backend P2P
scheduling path. The field is v4-only; schema 3 refuses it, and a v3 request
cannot carry profiles its own identity cannot express. Profile order is
identity-bearing because it determines `t000_p2p`, `t001_p2p`, and so on.

The ranks are **workload participant ranks** (`0..tp*pp*ep*dp-1`), not
topology endpoint IDs. A profile can address another participant, but it
cannot address a non-participant agent such as an HBM controller. The raw
trace path is endpoint-addressed and can; that is the path to use for an
initiator→memory-controller trace. Adding a new `traffic_class` also adds a
class to the VC assignment, so reuse an existing class if the design must
stay inside the 2-VC RTL preview slice.

The canonical profile path is network-only at the system level today. BookSim
evaluates `NETWORK_COMPLETION`; ASTRA's qualified execution path is
collective-mode (`et_granularity=collectives`) and refuses a `P2P` operation
with a typed `Astra2SemanticRefusal`. That is a real boundary, not a zero.
The raw trace path is also network-only. A target/memory service model and a
transaction-aware system model are separate layers.

## Replay a trace

```bash
veritx evaluate trace \
  --request /tmp/p3851-request.json \
  --trace /tmp/soc-mixed.trace \
  --out /tmp/soc-mixed-evidence.json \
  --run-dir /tmp/soc-mixed-run
```

The evidence document records the request design hash, fabric hash, trace
SHA-256, trace summary, route equivalence, qualification, and BookSim stats.
The run refuses a non-fresh `--run-dir`, a class column other than `0`, an
endpoint outside the compiled attachment, and a trace the standalone profile
cannot realize.

## Diagnostic mesh-DOR replay

The certified raw-trace seam is ANYNET-only, so a typed mesh is refused. For
a single-class trace on a typed `MeshIntent`, use the diagnostic bridge:

```bash
veritx evaluate mesh-trace \
  --request /tmp/p3851-request.json \
  --trace /tmp/soc-mixed.trace \
  --out /tmp/p3851-mesh-trace.json \
  --run-dir /tmp/p3851-mesh-trace
```

It compiles the request, requires `k*k == router_count`, builds the legacy
mesh `dim_order` config, runs BookSim, and writes
`mesh-trace-evaluation.json` labelled `DIAGNOSTIC_MESH_DOR` with
`exact_fabric_eligible=False`. It does not bind the compiled VC assignment or
route artifact, does not compare route dumps, and does not run ASTRA. On
p-3851 the 5,000-packet trace reports 8,661 completion cycles, 8.9 average
hops, and p50/p95/p99 of 489/4,129/4,314.

## What the profile actually models

- **Rate and burst** — an exact per-initiator token bucket in flits/cycle.
- **Outstanding** — a request holds a slot until `issue + response_latency`;
  this is a declared-latency bound, not protocol credit return.
- **Read/write mix** — an exact credit accumulator. A read emits a request and
  a response; a write emits a request and a one-flit acknowledgement.
- **Payload** — `ceil(payload_bytes * 8 / flit_width_bits)` flits, validated
  against the fabric's maximum packet size.
- **Targets** — deterministic round-robin over the declared endpoint set.

`protocol`, `qos_class`, and `latency_target_cycles` are validated and carried
as metadata, but they do not change the generated bytes. This path is
single-class; multi-class QoS priority remains on the canonical BookSim
projection, not here.

## Sensitivity result — the first controlled check did not reproduce the flip

An early diagnostic run on the native 9×9 mesh and torus (dim_order routing)
gave 8,661 vs 11,496 cycles for the same 5,000-packet trace, which looked like
a demand-shape flip against the collective catalog (11,720 vs 11,694).

A matched-routing comparison does **not** reproduce it. Using the same
min-hop anynet routing and the same VCS/buffers, across five demand mixes:

| Trace | Mesh | Torus | Cmesh | Fat-tree |
|---|---:|---:|---:|---:|
| Mixed | 8,170 | 8,160 | 12,581 | 20,155 |
| Read-heavy | 9,461 | 9,710 | 12,581 | 20,155 |
| Write-heavy | 8,170 | 8,160 | 12,581 | 20,155 |
| Uniform | 12,289 | 12,160 | 13,952 | 24,130 |
| Hotspot | 32,202 | 32,086 | 32,339 | 32,271 |

With a 1.5% relative indifference band:

- read-heavy: **mesh** wins by 2.6%
- mixed, write-heavy, uniform, hotspot: mesh/torus tie
- hotspot: all four topologies are within 1.5% — the fabric is saturated, so
  the topology choice barely matters
- cmesh and fat-tree are behind except under hotspot saturation
- no flips; four ties; `stable=False` because the top is not decisive

This is the first decision-accuracy result, and it is deliberately negative:
the new front end has not yet earned a claim that it changes the top fabric
decision. It quantifies the mesh/torus gap and confirms the cmesh/fattree
penalty. The multi-class collective trace also cannot run on the legacy
anynet path because that path binds one class; the canonical catalog remains
the multi-class reference. The next step is a native-routing matrix and a
wider workload set, not a stronger claim.

## Decision matrix and the indifference band

`analysis/decision_matrix.py` records one result per `(topology, trace,
config)`, ranks evaluated topologies, and reports winner stability. The
important addition is `tolerance`, an absolute cycle band:

```python
rankings(results, relative_tolerance=0.015)
stability(results, relative_tolerance=0.015)
```

Without a band, a 10-cycle difference on an 8,160-cycle run is reported as a
winner and the harness manufactures flips on noise. A 1.5% relative band is
the honest resolution for this model. The same evidence then says:

- read-heavy: mesh, by 2.6%
- mixed, write-heavy, uniform: mesh/torus tie
- hotspot: all four topologies within 1.5% (saturated)
- no flips; four ties; `stable=False` because the top is not decisive
- cmesh and fat-tree are behind except under saturation

That is the honest selection result: the model can separate the families, but
it cannot robustly distinguish mesh from torus on this workload set. The
product should present a tie/robust choice, not a false winner.

## Synthetic coherence

`workload/coherence_traffic.py` generates deterministic MSI miss-sequence
intents for the existing `CoherenceIntent` path:

```python
from veritx_dse.workload.coherence_traffic import (
    CoherenceTrafficSpec, apply_coherence_traffic,
)

spec = CoherenceTrafficSpec(
    world_size=64, homes=(0,), patterns=("READ_SHARED", "WRITE_INVALIDATE"),
    lines=4, line_bytes=64, intents_per_pattern=1, sharing_degree=4,
    writer=1, traffic_class="coherence", max_intents=16,
)
request = apply_coherence_traffic(base_request, spec)
```

Each intent lowers to one `KIND_COHERENCE` operation and the existing
REQ/RSP/SNP/ACK fanout (`2 * lines * len(sharers)` messages for both
patterns). A class named `coherence` or `coherence:*` pins to Plane C. This
is traffic shape only: no directory state, exclusivity, ownership transfer,
writeback races, cache hits, retries, or protocol correctness. There is no
temporal or rate model; all coherence operations lower at `step=0`.

## Deliberate limits

- No target/memory service model: the destination is a network endpoint, not a
  queue/bank service with latency and backpressure.
- No coherence: no snoop/home/filter behavior, no cache-line sharing, no
  protocol state.
- No transaction-level ordering, retries, or read-response dependencies.
- No calibration against silicon or RTL. A trace-driven number is only as good
  as the trace and the model behind it.

The next layers are a generic target/memory service model and synthetic
coherence patterns; neither is claimed here.
