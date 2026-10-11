# Multicast source-replication modelling

`WorkloadGraph` MULTICAST intents distinguish `SOURCE_REPLICATION` from
`HARDWARE_REPLICATION`. The standard logical-message and physical-traffic
projection currently lowers only `SOURCE_REPLICATION`: N declared destinations
each receive a separate full-payload logical unicast. The source logical
payload is B bytes; source-injected and modeled destination payload are N × B
bytes. A semantic BROADCAST remains a COLLECTIVE with its own schedule; neither
intent by itself implies router branching or in-network reduction.

`LogicalMessageArtifactV2.multicast_records()` and the corresponding V3
method independently check intent-to-replica coverage, ordering, source,
payload, phase, class and unique message/sequence identities. V3 requires
explicit traffic-class assignment for every communicating operation,
including MULTICAST and P2P; it never infers a class from a destination.

`PhysicalTrafficArtifactV2.multicast_ledger()` (also inherited by V3)
revalidates replica identities and rank→agent→endpoint bindings, exact packet
payload/flit/header/padding decomposition, and exposes each replica's
message ID, destination rank/endpoint and packet records. It labels the
scope `MODELED_SOURCE_REPLICATION_ONLY` / `replicated_unicast`.
`delivered_payload_bytes` describes modeled destination demand, **not observed
completion**. No physical link sharing, fork tree, setup costs, latency,
capacity, progress, simulator equivalence or qualification is claimed.

A bounded native diagnostic consumes an authored `HARDWARE_REPLICATION`
operation. `NativeMulticastRequest.from_compiled()` binds its operation
identity, destination ranks, authored source-router replication point, traffic
class, `MappingArtifact` placements and compiled endpoint routers. The native
BookSim driver forks real branch flits through the ordinary router-buffer/VC/link
path. Evidence checks branch identity, per-destination retirement, route
continuity (including destination eject), physical link-flit conservation, and
drain.

The diagnostic is exposed through the product revision-experiment endpoint as
`NATIVE_MULTICAST_SOURCE_ROUTER_DIAGNOSTIC_V1`; it remains a separate
operation-level profile, not part of ordinary replicated-unicast projection or
the coupled tensor DAG. Build the engines with
`scripts/build_native_coupled_diagnostic.py --booksim-only <new-disk-backed-directory>`.
An operator configures the generated `native-multicast-config.json` as
`VERITX_NATIVE_MULTICAST_CONFIG` on the product service; callers submit only
the compiled revision, `WorkloadGraph`, `MappingArtifact`, and operation ID.
The config binds a BookSim source inventory and a local build record to the
executable. That record is replay-checked and is **not** a signed/remote build
attestation. Call `NativeMulticastEvidence.revalidate()` or repeat the product
request for a fresh engine execution; matching evidence is still diagnostic,
not qualification or hardware equivalence.

This diagnostic does not change the standard logical-message or
`PhysicalTrafficArtifact` projection: `SOURCE_REPLICATION` still means
replicated unicast, while `HARDWARE_REPLICATION` is refused by that projection
rather than mislabeled. The older `archive/booksim-ext/multicast.patch` is a
separate TrafficManager experiment and does not supply the current authored
operation binding or real branch-link accounting.

These ledgers are derived views, not new persisted identity fields. Existing
strict loaders still rebuild logical/physical artifacts from verified parents
and reject modified serialized records. This does not add V3 product storage
or job/API support.

Run executable positive and negative checks from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tracks/t3-topology/dse \
python -m pytest -q -p no:cacheprovider \
  tracks/t3-topology/dse/tests/test_multicast_replication.py \
  tracks/t3-topology/dse/tests/test_rcu_multicast_report_safety.py \
  tracks/t3-topology/dse/tests/test_backend_booksim_projection.py \
  --basetemp=/tmp/veritx-multicast-example
```

Checks exercise one/multiple destinations; V2/V3 classes; exact byte and
independent integer packet/flit laws; parent-recomputed reload; missing,
duplicate, wrong-rank/class/payload/binding/packet replicas; and forbidden
hardware replication. Backend projection checks retain separate unicast
streams and prohibit native multicast/fork configuration.

RCU physical modelling remains unavailable under ROUTE-011: arithmetic,
contributor/epoch protocol, placement and cost contracts are absent. Legacy
`rcu_enabled=True`, hardware multicast group/setup requests and RCU area flags
or nonzero counts produce typed missing-capability refusals instead of ordinary
fabric or fictitious estimates. None/false RCU flags remain nonrequesting
compatibility values. Ordinary legacy reports do not assume ideal multicast;
hypothetical message-saving comparisons are explicitly not canonical execution.

The standalone diagnostic binds an authored destination set and replication
point to observed branch-resource evidence; it is not yet integrated into the
general DSE scheduler/product path. Standard source-replicated workload
records remain explicitly labeled `replicated_unicast`.

All dirty-tree evidence is diagnostic only. No RTL, UVM, physical signoff,
producer-bound canonical multicast execution or simulator qualification is added.
