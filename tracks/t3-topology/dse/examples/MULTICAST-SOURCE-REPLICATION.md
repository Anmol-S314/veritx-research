# Multicast source-replication modelling

Canonical `WorkloadGraph` MULTICAST operations support only
`SOURCE_REPLICATION`: N declared destinations each receive a separate
full-payload logical unicast. The source logical payload is B bytes;
source-injected and modeled destination payload are N × B bytes. A semantic
BROADCAST remains a COLLECTIVE with its own schedule; neither implies router
branching or in-network reduction.

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

All dirty-tree tests are diagnostic only. No RTL, UVM, physical signoff, native
multicast/RCU execution or simulator qualification is added.
