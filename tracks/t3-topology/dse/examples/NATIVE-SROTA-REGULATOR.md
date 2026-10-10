# Native simulator-owned SROTA regulator diagnostic

`NATIVE_SROTA_REGULATOR_DIAGNOSTIC_V1` executes an opt-in instrumented **native
simulator**, not `ABSTRACT_LOCAL_ISLAND_V1`. The latter has different rate-zero,
initial-token, admission, service and credit semantics and is not its oracle.
No canonical intent, capability/qualification registry, existing binary or
manifest is changed by this experiment API.

## Explicit envelope

Actual projection parents provide canonical topology, seats, mapping, route,
VC/packet format and logical/physical traffic identities. Only D+optional T,
sidebuf, islands, both direct shapes, column-first island routing, no Valiant or
deflection, one native traffic class and nonempty single-flit packets are
supported. The existing SROTA **multiclass refusal remains intact**. Synthetic
multi-class ledger tests demonstrate checker isolation only, not live native
multiclass integration.

The caller declares every existing class's positive exact `Fraction` dyadic
rate (<=1, denominator<=65536), integer burst 1..65536, seed, explicit BYPASS
boolean, sidebuffer depth 1..16 and finite cycle horizon <=1,000,000. Depth 1
is a simulator stress case, **not a hardware capacity claim**. Native buckets
start full. BYPASS renders explicit zero rates (native zero means unregulated,
not no-refill). The overlay records all three native regulator knobs and class
name->native-rank mapping in its separate identity.

The caller supplies one nonnegative, nondecreasing arrival cycle per canonical
packet, strictly below the horizon. Only timestamps change; original ordered
packet source/class/destination/size and physical demand remain exact. Equal
arrivals retain canonical row order. Native trace injection uses a shared
physical source port, per-source FIFO and downstream backpressure; arrival is
eligibility, not guaranteed injection. Original traffic/geometry prepared IDs,
retimed trace/config digests, schedule and horizon are bound separately.
**Retimed output is not original canonical workload timing.**

Experiment-owned native profile choices: islip VC/switch allocation, one
iteration, speculative switch allocation with native eligibility/credit checks,
unit routing/VC/switch/credit/final traversal delays, prepare delay 0, unit
input/output/internal speedup, no packet switch hold, watermark depth-1,
max_samples=1, warmup=0. Sampling period is the lesser of the original prepared
period and the diagnostic horizon. Values are bound in executed config identity.
The standard prepared `traffic=trace(...)` path uses base `TrafficManager`,
NOT `TraceTrafficManager`. Sampling controls **do not bound trace drain**.
The opt-in default-zero `srota_diagnostic_max_cycles` guard bounds actual
`_Step` execution through sampling AND drain. Horizon exhaustion prints pending
packets, in-flight flits and source-held flits and refuses PASS; it is not a
proof of deadlock. Missing/partial/malformed telemetry likewise refuses.

## Measured event agreement

`SrotaLedger` rows contain router, contiguous per-router sequence, native cycle,
event, class, flit, input-VC slot, pre/post balance, refill delta and sidebuffer
occupancy. Begin/init/step-begin/step-end/end delimit coverage. Native events
observe refill, reserve, spend, defer, same-step END refund, gate-observed
arrive/grant, allocation loss, capture/full/drain, early/ordinary credit decision
and buffered/unbuffered departure. The corrected header now agrees with the
executable same-step refund semantics.

The checker replays exact dyadic balances/caps and concrete reservation holds,
class/router sharing, same-step spend/refund, every positive-rate refill,
sidebuffer occupancy/capacity/input-VC identity and exactly one upstream credit
decision per router/flit (early capture credit, **no second buffered credit**).
A geometry oracle independently checks total switch departures = sum over each
packet of `1 + unequal_x + unequal_y`; aggregate allocation-loss/sidebuffer and
per-class arrival/grant/deferral rows must match the event ledger. Complete
traces must drain sidebuffers/holds, match every grant/arrival/spend/departure and
conserve all declared injected/accepted packets/flits. Positive regulation must
actually spend and defer. Replay of stored evidence revalidates actual parents,
config/trace, native binary bytes, source inventory and complete logs.

These are observed simulator accounting laws, **not independent allocator
schedule prediction**, fabric timing equivalence, fairness, full staging-buffer
arrival/credit-channel timing proof or hardware equivalence. Downstream-credit
masking before the active gate is native code behavior; this ledger does not
observe every masked request. A source inventory binds observed input contents;
it does not prove clean provenance or itself prove which inputs built arbitrary
binary bytes. External snapshot/build comparison and logs supply diagnostic
build evidence; no producer pin or clean/reusable qualification is asserted.

## Runnable diagnostic (builds externally, never skips native acceptance)

From repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tracks/t3-topology/dse \
python -m pytest -q -p no:cacheprovider \
  tracks/t3-topology/dse/tests/test_native_srota_regulator.py \
  --basetemp=/tmp/veritx-native-srota-example
```

The test copies only inventoried native producer inputs to an external build,
requires make/g++/flex/bison, builds there, compares source inventories, then
executes explicit hotspot demand against real compiled SROTA seats/resources.
It compares throttled and bypass versions of the **same** retimed 248 single-flit
P2P packets; exercises observed allocation-loss refunds, captures/drains,
strict depth-1 full-buffer backpressure, original schedule, finite incomplete
run, malformed/tampered evidence and retained multiclass refusal. Logs,
binary/build log and evidence stay under the external pytest directory.
An explicit `VERITX_SROTA_DIAGNOSTIC_BINARY` may reuse a diagnostic build for
regressions; the acceptance build should omit it. Neither mode is qualification.

The API is `prepare_native_regulator(parents, rates=..., burst=..., seed=...,
bypass=..., arrival_cycles=..., horizon=..., sidebuf_depth=...)`, followed by
`run_native_regulator(experiment, parents=..., binary=..., source_root=...,
source_inventory=..., run_dir=...)`. Create source inventory with
`native_source_inventory(source_root)`; `run_dir` must not already exist.
No defaults invent workload arrivals, class rates or island attach service.
