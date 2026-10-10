# Connected native tensor diagnostic V1

`execute_native_coupled_tensor(compilation, workload, policy, placement,
native_config)` runs **actual BookSim and Ramulator engines** on one exact
Fraction timebase. It reuses the coupled workload's logical DAG, compute
capacity and host byte-image contracts, not the abstract network/service
executor. The profile is `NATIVE_COUPLED_TENSOR_DIAGNOSTIC_V1`.

## Build and run

Build only isolated vendor copies on disk (not full repository snapshots):

```bash
python scripts/build_native_coupled_diagnostic.py "$HOME/.cache/veritx-native-build-1"
export VERITX_NATIVE_COUPLED_CONFIG="$HOME/.cache/veritx-native-build-1/native-config.json"
export PYTHONPATH=tracks/t3-topology/dse
python -m veritx_dse.backend.native_coupled \
  tracks/t3-topology/dse/examples/native_coupled_tensor_v5.json \
  "$VERITX_NATIVE_COUPLED_CONFIG"
python -m pytest -q tracks/t3-topology/dse/tests/test_native_coupled.py
```

The build directory must be new, outside the checkout and `/tmp`. Requires
CMake, C++, flex/bison, Python development headers and the existing vendor
dependency sources. Builds use `-j1`, no downloads or producer re-pins. Source
file manifests and executable/library hashes are checked before and after
execution. Build commands, source HEAD **and actual dirty status** are retained.
The extension is compiled for the running Python ABI, not assumed compatible
with an older CPython extension. Filesystem/source pins are diagnostic provenance,
not independent source-to-binary attestation or release qualification.

## What is connected

1. Validate the immutable V5 design/system/workload and placement identities,
   native mesh route/attachment/VC envelope, policy, transaction layout and
   full native backing-burst decode/authorization before issuing a child.
2. Reserve bounded host target slots and compiled initiator outstanding credits.
   Inject actual BookSim packets, retaining the returned native PID.
3. Request-tail retirement makes the child eligible at a **strictly future**
   memory edge. `send(false)` retains the same child and reservation, retries
   admission only on later memory edges and never reinjects its request packet.
4. Register callback correlation before `send`, including synchronous WRITE
   ACKs. Successful native callbacks commit the corresponding host byte write
   or READ snapshot exactly once. Callbacks do not re-enter the network.
5. Inject an actual response at a strictly future network edge. Response-tail
   retirement releases the child credit; all access children must retire before
   dependent compute starts. Authored compute completion releases later writes.

A native step ending at edge `t` makes that step's completion visible at `t`.
Both engines' coincident completions precede cross-engine admission. BookSim
retirement cycle `atime` is checked against `(atime + 1) * network_period`.
Network and memory periods may differ; fractional picosecond network periods
are retained exactly. This is a deterministic host clock bridge, **not hardware
CDC or a simulation of undeclared FIFO crossings**.

The example executes READ -> compute -> WRITE -> READ-back. Native flit/tail
and memory-admission counters are reconciled with request/PID/callback ownership.
Evidence includes exact intervals, source-held child identities, live credits,
committed/returned bytes, final images and full input identities.
`observed.native_network` / `observed.native_memory` are derived from real
counters, not declared constants. Replay creates
fresh actual engines; `.from_dict` rejects even a rehashed forged report rather
than relying on a self-consistent digest alone.

## Closed initial envelope

- Square identity-attached mesh, <=64 routers, deterministic DOR_XY, default
  IQ router, one class and one identity-transition VC; one packet per request
  and response. Authored/advanced router controls refuse rather than disappear.
- One explicitly mapped HBM controller, one host-visible contiguous physical
  window and 32-byte transactions. The native RoBaRaCoCh mapper still scatters
  that window across pseudochannels/SIDs/bankgroups/banks, so the window is a
  host-side containment check, not a native bank/channel locality claim. Bounded
  FRFCFS/Open/AllBank configuration. All declared tensor storage must fit it.
- Homogeneous endpoint transaction/fabric clocks, explicit RELAXED ordering
  with access-completion dependencies, and compiled outstanding limits.
- <=4096 children and <=100,000 planned flits; bounded host staging, memory
  outstanding count, native engine steps and event-ledger allocation.
- BYPASS only. Native service replaces reference `service_cycles`, which must
  explicitly be zero. Compute durations remain authored compiled-clock cycles.

The driver refuses local accesses (the remote projection refuses issuer == target
before any engine opens), multiple owners/controllers, replicas,
interleaving/migration, requester/owner caches, non-READ/WRITE transaction kinds,
atomics/MMIO, reordering, retry/reset, declared crossings, power/sideband
and advanced network execution.
It does not combine independent simulator totals or silently use a reference
network/memory timing fallback.

## Claims and limits

Native **packet and DRAM timing** are executed. Tensor values remain **host
reference bytes**, not stored/transmitted native DRAM or AXI/CHI payload data.
WRITE callbacks mean controller ACK/possible coalesced acceptance, not physical
persistence. Host target-slot reservations are `RESERVATION_ADMISSION_V1`, not
genuine native receiver/ejection-credit backpressure. COMPLETE proves all DAG
nodes and host responses retired with no live flits/host credits; it is not a
reset-credit-drain proof or physical DRAM quiescence proof.

The retained HBM2 timing configuration contains simulator assumptions; no
hardware calibration, protocol equivalence, accuracy, qualification, RTL/UVM,
metastability, physical timing or signoff is claimed. Placement is validated
against the resource graph but never read for timing; the executed attachment is
identity-bound. File pins are hashed before and after the run, which is **not** a
binding between a hash and the exact bytes executed (an adversary with write
access could swap and restore). The generic Studio experiment API
still refuses this native profile; it is currently an explicit backend/CLI path,
not a promoted product capability. Independent review and qualification gates
remain outstanding.

Unit phase oracles are labeled synthetic. Actual-engine tests require explicit
`VERITX_NATIVE_COUPLED_CONFIG` pins and otherwise skip with a stated reason;
skipped tests must never be reported as native acceptance, and a dedicated test
fails the run under `CI` when the pins are absent so coverage cannot silently
vanish. Live tests cover
conservation, admission backpressure without network reinjection, dependent
compute feedback, fractional clocks, synchronous callback handling, bounded
horizon visibility, input/evidence tamper rejection and fresh-process replay.
