"""W6 connected reference scenario over the shared coupled executor.

This adapter binds and checks the supported reference composition (multiplane,
MSI, power lifecycle, and authored faults). It does not certify native
multicast, RCU, or hardware behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from veritx_dse.core.artifact import FrozenMap, canonical_bytes, content_id, thaw
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput, UnsupportedSemantics

PROFILE = "EXECUTION_CLOSURE_REFERENCE_V1"


@dataclass(frozen=True)
class ExecutionClosureEvidence:
    data: FrozenMap

    def artifact_id(self):
        return content_id("veritx/ExecutionClosureEvidence/v1", self.data)

    def to_dict(self):
        return {**thaw(self.data), "artifact_id": self.artifact_id()}

    def revalidate(self, *, compilation, workload, policy, placement, faults):
        expected = execute_w6_reference_scenario(
            compilation, workload, policy, placement, faults)
        if self != expected:
            raise EvidenceInvalid("W6 evidence differs from parent-recomputed scenario")

    @classmethod
    def from_dict(cls, document, *, compilation, workload, policy, placement, faults):
        expected = execute_w6_reference_scenario(
            compilation, workload, policy, placement, faults)
        if canonical_bytes(document) != canonical_bytes(expected.to_dict()):
            raise EvidenceInvalid("stored W6 evidence differs from parent-recomputed scenario")
        return expected


def _clock_rates(compilation):
    domains = compilation.compiled_system.clock_domains
    return {row.id: row.frequency_hz for row in domains.domains}


def _has_cross_plane_overlap(phases):
    by_plane = {0: [], 1: []}
    for phase in phases:
        if phase.get("resource", [None])[0] != "channel":
            continue
        resource = phase["resource"]
        if len(resource) != 3 or resource[1] not in by_plane:
            continue
        start = Fraction(phase["start_s"]["numerator"], phase["start_s"]["denominator"])
        end = Fraction(phase["completed_s"]["numerator"], phase["completed_s"]["denominator"])
        by_plane[resource[1]].append((start, end))
    return any(max(a0, b0) < min(a1, b1)
               for a0, a1 in by_plane[0] for b0, b1 in by_plane[1])


def _expected_final_images(workload):
    images = {tensor_id: bytearray.fromhex(value)
              for tensor_id, value in workload.initial_images}
    values = dict(workload.access_values)
    write_ranges = {tensor_id: [] for tensor_id in images}
    for access in workload.demand.accesses:
        if access.kind.value != "WRITE":
            continue
        try:
            payload = bytes.fromhex(values[access.access_id])
        except (KeyError, ValueError):
            raise EvidenceInvalid(
                f"W6 write {access.access_id!r} lacks canonical authored bytes") from None
        if len(payload) != access.count * access.block_bytes:
            raise EvidenceInvalid(
                f"W6 write {access.access_id!r} payload length differs from its blocks")
        image = images[access.tensor_id]
        for block in range(access.count):
            source = block * access.block_bytes
            destination = access.offset_bytes + block * access.stride_bytes
            write_ranges[access.tensor_id].append(
                (destination, destination + access.block_bytes, access.access_id))
            image[destination:destination + access.block_bytes] = \
                payload[source:source + access.block_bytes]
    for tensor_id, ranges in write_ranges.items():
        ordered = sorted(ranges)
        for previous, current in zip(ordered, ordered[1:]):
            if previous[1] > current[0]:
                raise UnsupportedSemantics(
                    f"W6 writes {previous[2]!r} and {current[2]!r} overlap in "
                    f"tensor {tensor_id!r}; final bytes depend on write arbitration")
    return {tensor_id: bytes(image).hex() for tensor_id, image in images.items()}


def execute_w6_reference_scenario(compilation, workload, policy, placement, faults):
    """Execute and seal the required connected reference profile once.

    The caller authors the complete scenario in ``workload`` and ``faults``;
    this function never infers clocks, routes, power policies, or losses.
    """
    from veritx_dse.application.coupled_tensor import execute_coupled_tensor
    from veritx_dse.application.data_movement import FaultProfile

    if compilation.multi_plane_vc is None or compilation.control_plane is None:
        raise UnsupportedSemantics("W6 requires the compiled Plane-D/Plane-C binding")
    if workload.msi_profile is None:
        raise UnsupportedSemantics("W6 requires an explicit bounded MSI profile")
    if not workload.power_policies:
        raise UnsupportedSemantics("W6 requires explicit domain power/reset policies")
    if not isinstance(faults, FaultProfile):
        raise InvalidInput("W6 requires an explicit FaultProfile")
    if not faults.dropped_responses or not faults.dropped_protocol_messages:
        raise UnsupportedSemantics(
            "W6 requires both a lost response and an authored protocol-ACK loss")
    execution = execute_coupled_tensor(
        compilation, workload, policy, placement, faults).to_dict()
    if execution.get("status") != "COMPLETE":
        raise EvidenceInvalid(
            f"W6 reference scenario did not complete: {execution.get('status')}")
    summary = execution["summary"]
    if (summary["children_live"] != 0
            or summary["children_committed"] != summary["children_responded"]
            or summary["fifo_words_reserved_written"]
            != summary["fifo_words_reserved_read"]):
        raise EvidenceInvalid("W6 completion left requests, credits, or FIFO words live")
    plane_traffic = summary.get("plane_traffic")
    if not isinstance(plane_traffic, dict) or set(plane_traffic) != {"0", "1"}:
        raise EvidenceInvalid("W6 requires exact traffic counters for both compiled planes")
    observed_plane_link_flits = {0: 0, 1: 0}
    for phase in execution.get("phases", ()):
        resource = phase.get("resource", ())
        if not resource or resource[0] != "channel":
            continue
        if (len(resource) != 3 or type(resource[1]) is not int
                or resource[1] not in observed_plane_link_flits):
            raise EvidenceInvalid("W6 channel phase has an invalid compiled-plane resource key")
        flits = phase.get("flits")
        if type(flits) is not int or flits < 1:
            raise EvidenceInvalid("W6 channel phase has an invalid flit count")
        observed_plane_link_flits[resource[1]] += flits
    plane_conservation = {}
    for plane in (0, 1):
        name = str(plane)
        counters = plane_traffic[name]
        if (not isinstance(counters, dict)
                or set(counters) != {"routed_flits", "planned_link_flits", "link_flits"}
                or any(type(value) is not int or value < 0 for value in counters.values())
                or counters["link_flits"] < 1):
            raise EvidenceInvalid(f"W6 plane {plane} traffic counters are malformed or empty")
        observed = observed_plane_link_flits[plane]
        if observed != counters["link_flits"]:
            raise EvidenceInvalid(
                f"W6 plane {plane} channel-phase flits differ from its summary link counter")
        plane_conservation[name] = {
            "phase_link_flits": observed,
            "summary_link_flits": counters["link_flits"],
            "planned_link_flits": counters["planned_link_flits"],
            "routed_flits": counters["routed_flits"],
            "phase_summary_equal": True,
            "planned_count_is_retry_exclusive_baseline": True,
        }
    if not _has_cross_plane_overlap(execution["phases"]):
        raise EvidenceInvalid("W6 did not overlap data-plane and control-plane channel work")
    resource_owners = {}
    for row in execution["phases"]:
        resource = tuple(row.get("resource", ()))
        owner = (row.get("parent"), row.get("sequence"))
        resource_owners.setdefault(resource, set()).add(owner)
    shared_wait = any(
        row.get("resource", [None])[0] in ("interface", "crossing", "service", "channel")
        and len(resource_owners.get(tuple(row.get("resource", ())), ())) > 1
        and Fraction(row.get("resource_wait_s", {}).get("numerator", 0),
                     row.get("resource_wait_s", {}).get("denominator", 1)) > 0
        for row in execution["phases"])
    if not shared_wait:
        raise EvidenceInvalid(
            "W6 did not observe positive blocking behind an already-reserved shared resource")
    transactions = execution.get("msi_transactions", [])
    if (not transactions
            or any(row["state"] != "COMMITTED"
                   or row.get("transient_states") for row in transactions)):
        raise EvidenceInvalid("W6 left an MSI transaction or transient unresolved")

    # Replay committed directory snapshots in ledger order. A global drain
    # reset clears directory state; domain-local resets preserve the declared
    # MSI state. Snapshots are captured only after each home transition commits.
    transactions_by_id = {}
    for transaction in transactions:
        transaction_id = transaction.get("transaction")
        if not isinstance(transaction_id, str) or transaction_id in transactions_by_id:
            raise EvidenceInvalid("W6 MSI transaction identities are missing or duplicated")
        transactions_by_id[transaction_id] = transaction
    ledger = execution.get("ledger")
    if not isinstance(ledger, list):
        raise EvidenceInvalid("W6 has no ordered execution ledger")
    expected_directory = {}
    committed_transactions = set()
    for event in ledger:
        if event.get("event") == "reset_complete":
            expected_directory.clear()
            continue
        if event.get("event") != "msi_transaction_commit":
            continue
        transaction_id = event.get("id")
        transaction = transactions_by_id.get(transaction_id)
        if transaction is None or transaction_id in committed_transactions:
            raise EvidenceInvalid("W6 ledger has an unknown or duplicate MSI commit")
        snapshots = transaction.get("committed_directory")
        if not isinstance(snapshots, list) or not snapshots:
            raise EvidenceInvalid("W6 committed MSI transaction has no directory snapshot")
        committed_transactions.add(transaction_id)
        for snapshot in snapshots:
            line = snapshot.get("line")
            if not isinstance(line, list) or len(line) != 3:
                raise EvidenceInvalid("W6 MSI commit snapshot has an invalid line identity")
            expected_directory[tuple(line)] = {
                "state": snapshot.get("state"),
                "sharers": snapshot.get("sharers"),
                "dirty_owner": snapshot.get("dirty_owner"),
                "dirty_data": snapshot.get("dirty_data"),
            }
    if committed_transactions != set(transactions_by_id):
        raise EvidenceInvalid("W6 MSI transaction records and commit ledger differ")

    final_directory_rows = execution.get("msi_directory_projected")
    if not isinstance(final_directory_rows, list):
        raise EvidenceInvalid("W6 has no final MSI directory projection")
    final_directory = {}
    line_bytes = workload.msi_profile.line_bytes
    for entry in final_directory_rows:
        line = entry.get("line")
        if not isinstance(line, list) or len(line) != 3:
            raise EvidenceInvalid("W6 final MSI directory has an invalid line identity")
        key = tuple(line)
        if key in final_directory:
            raise EvidenceInvalid("W6 final MSI directory duplicates a line")
        state, sharers = entry.get("state"), entry.get("sharers")
        owner, dirty_data = entry.get("dirty_owner"), entry.get("dirty_data")
        if (not isinstance(sharers, list)
                or any(not isinstance(item, str) for item in sharers)
                or len(set(sharers)) != len(sharers)
                or sharers != sorted(sharers)):
            raise EvidenceInvalid("W6 final MSI sharer set is malformed")
        if state == "I":
            legal = not sharers and owner is None and dirty_data is None
        elif state == "S":
            legal = bool(sharers) and owner is None and dirty_data is None
        elif state == "M":
            try:
                dirty_bytes = bytes.fromhex(dirty_data) if isinstance(dirty_data, str) else b""
            except ValueError:
                dirty_bytes = b""
            legal = (len(sharers) == 1 and owner == sharers[0]
                     and len(dirty_bytes) == line_bytes
                     and dirty_data == dirty_data.lower())
        else:
            legal = False
        if not legal:
            raise EvidenceInvalid("W6 final MSI directory has illegal I/S/M ownership")
        final_directory[key] = {
            "state": state, "sharers": sharers,
            "dirty_owner": owner, "dirty_data": dirty_data}
    for entry in expected_directory.values():
        # Validate committed snapshots with the same directory ownership rules.
        state, sharers = entry["state"], entry["sharers"]
        owner, dirty_data = entry["dirty_owner"], entry["dirty_data"]
        if (not isinstance(sharers, list)
                or any(not isinstance(item, str) for item in sharers)
                or len(set(sharers)) != len(sharers)
                or sharers != sorted(sharers)):
            raise EvidenceInvalid("W6 committed MSI snapshot has malformed sharers")
        if state == "I":
            legal = not sharers and owner is None and dirty_data is None
        elif state == "S":
            legal = bool(sharers) and owner is None and dirty_data is None
        elif state == "M":
            try:
                dirty_bytes = bytes.fromhex(dirty_data) if isinstance(dirty_data, str) else b""
            except ValueError:
                dirty_bytes = b""
            legal = (len(sharers) == 1 and owner == sharers[0]
                     and len(dirty_bytes) == line_bytes
                     and dirty_data == dirty_data.lower())
        else:
            legal = False
        if not legal:
            raise EvidenceInvalid("W6 committed MSI snapshot has illegal I/S/M ownership")
    if final_directory != expected_directory:
        raise EvidenceInvalid(
            "W6 final MSI ownership differs from the last committed directory transitions")

    nodes = {node.node_id: node for node in workload.nodes}
    dependencies, _ancestors = workload.dependency_ancestors()
    completion_event = {
        "ACCESS": "access_complete", "COMPUTE": "compute_complete",
        "BARRIER": "barrier_complete", "DRAIN_RESET": "reset_complete",
        "DOMAIN_SLEEP": "domain_sleep_complete",
        "DOMAIN_WAKE": "domain_wake_complete",
        "DOMAIN_RESET": "domain_reset_complete",
    }
    completion_order = {}
    for node_id, node in nodes.items():
        expected_event = completion_event.get(node.kind)
        if expected_event is None:
            raise EvidenceInvalid(f"W6 has no completion event for node kind {node.kind!r}")
        matches = [(index, row) for index, row in enumerate(ledger)
                   if row.get("event") == expected_event and row.get("id") == node_id]
        if len(matches) != 1:
            raise EvidenceInvalid(
                f"W6 node {node_id!r} must complete exactly once in the ledger")
        ledger_index, row = matches[0]
        time = Fraction(row["time_s"]["numerator"], row["time_s"]["denominator"])
        completion_order[node_id] = (time, ledger_index)
    dependency_edges = sorted((dependency, node_id)
                              for node_id, required in dependencies.items()
                              for dependency in required)
    for dependency, node_id in dependency_edges:
        if not completion_order[dependency] < completion_order[node_id]:
            raise EvidenceInvalid(
                f"W6 dependency {dependency!r} did not complete before {node_id!r}")
    if (summary.get("nodes_completed") != len(nodes)
            or execution.get("pending_nodes")
            or execution.get("blocked_dependencies")):
        raise EvidenceInvalid("W6 DAG did not complete every authored node and dependency")

    read_ids = {row.get("access_id") for row in transactions
                if row.get("kind") == "READ"}
    write_ids = {row.get("access_id") for row in transactions
                 if row.get("kind") == "WRITE"}
    access_kinds = {access.access_id: access.kind.value
                    for access in workload.demand.accesses}
    expected_reads = {access_id for access_id, kind in access_kinds.items()
                      if kind == "READ"}
    expected_writes = {access_id for access_id, kind in access_kinds.items()
                       if kind == "WRITE"}
    if (not read_ids or not write_ids or read_ids != expected_reads
            or write_ids != expected_writes
            or any(row.get("access_id") not in access_kinds
                   or access_kinds[row.get("access_id")] != row.get("kind")
                   for row in transactions)):
        raise EvidenceInvalid(
            "W6 requires executed MSI READ/WRITE transactions bound to authored accesses")
    access_values = dict(workload.access_values)
    read_results = execution.get("read_results")
    if not isinstance(read_results, dict) or not read_results:
        raise EvidenceInvalid("W6 has no observed read-result map")
    for access_id in sorted(read_ids):
        result = read_results.get(access_id)
        expected = access_values.get(access_id)
        if (not isinstance(result, dict) or not result.get("complete")
                or result.get("hex") is None or expected is None
                or bytes.fromhex(result["hex"]) != bytes.fromhex(expected)):
            raise EvidenceInvalid(
                f"W6 MSI READ {access_id!r} differs from authored expected bytes")
    expected_images = _expected_final_images(workload)
    if execution.get("final_images") != expected_images:
        raise EvidenceInvalid("W6 final images differ from the authored writes")
    expected_image_id = content_id("veritx/ByteImage/v1", expected_images)
    if execution.get("final_image_id") != expected_image_id:
        raise EvidenceInvalid("W6 final image identity does not bind the verified bytes")

    attempts = [row for child in execution["children"]
                for row in child.get("attempt_log", ())]
    if (not any(row["event"] == "protocol_ack_dropped" for row in attempts)
            or not any(row["event"] == "response_dropped" for row in attempts)):
        raise EvidenceInvalid("W6 did not observe both authored loss controls")

    endpoint_contract = {
        row["endpoint_id"]: row
        for row in compilation.compiled_system.execution_contract.endpoints}
    used_endpoints = {endpoint for child in execution["children"]
                      for endpoint in (child.get("initiator"), child.get("target"))}
    if not used_endpoints or not used_endpoints <= set(endpoint_contract):
        raise EvidenceInvalid("W6 issued children do not bind to compiled endpoint contracts")
    used_clock_names = {
        name for endpoint in used_endpoints
        for name in (endpoint_contract[endpoint].get("transaction_clock_domain"),
                     endpoint_contract[endpoint].get("fabric_clock_domain"))}
    clock_rates = _clock_rates(compilation)
    if (None in used_clock_names or not used_clock_names <= set(clock_rates)
            or len({clock_rates[name] for name in used_clock_names}) < 2):
        raise UnsupportedSemantics(
            "W6 requires two distinct rates among issued-child endpoint transaction/fabric clocks")
    endpoint_phases = [row for row in execution["phases"]
                       if row.get("endpoint_id") in used_endpoints
                       and row.get("resource", [None])[0] in ("interface", "crossing")]
    if not endpoint_phases:
        raise EvidenceInvalid("W6 endpoint clock evidence is not present in executed interface phases")
    observed_clocks = {clock for row in endpoint_phases
                       for clock in (row.get("source_clock"), row.get("destination_clock"),
                                     row.get("fabric_clock_domain"))
                       if clock is not None}
    if not used_clock_names <= observed_clocks:
        raise EvidenceInvalid("W6 used endpoint clocks are absent from the executed network schedule")

    control_trace = execution.get("power_control_trace", ())
    lifecycle = None
    nodes_by_id = {node.node_id: node for node in workload.nodes}
    domains = {row.get("domain_id") for row in control_trace
               if row.get("event") == "sleep_complete"}
    ledger = execution.get("ledger", ())
    for domain in sorted(d for d in domains if d is not None):
        sleeps = [row for row in control_trace
                  if row.get("event") == "sleep_complete" and row.get("domain_id") == domain]
        wakes = [row for row in control_trace
                 if row.get("event") == "interrupt_wake" and row.get("domain_id") == domain]
        resets = [row for row in control_trace
                  if row.get("event") == "domain_reset_assert" and row.get("domain_id") == domain]
        releases = [row for row in control_trace
                    if row.get("event") == "domain_reset_release" and row.get("domain_id") == domain]
        if not (len(sleeps) == len(wakes) == len(resets) == len(releases) == 1):
            continue
        sleep, wake, reset, release = sleeps[0], wakes[0], resets[0], releases[0]
        wake_done = [row for row in ledger
                     if row.get("event") == "domain_wake_complete"
                     and row.get("id") == wake.get("node_id")
                     and row.get("domain_id") == domain]
        reset_interval = next((row for row in execution.get("reset_intervals", ())
                               if row.get("node_id") == reset.get("node_id")
                               and row.get("domain_id") == domain), None)
        lifecycle_nodes = (nodes_by_id.get(sleep.get("node_id")),
                           nodes_by_id.get(wake.get("node_id")),
                           nodes_by_id.get(reset.get("node_id")))
        if (any(node is None or node.power_domain_id != domain for node in lifecycle_nodes)
                or lifecycle_nodes[0].kind != "DOMAIN_SLEEP"
                or lifecycle_nodes[1].kind != "DOMAIN_WAKE"
                or lifecycle_nodes[2].kind != "DOMAIN_RESET"
                or len(wake_done) != 1 or reset_interval is None):
            continue
        sleep_time = Fraction(sleep["time_s"]["numerator"], sleep["time_s"]["denominator"])
        wake_start = Fraction(wake["start_s"]["numerator"], wake["start_s"]["denominator"])
        wake_done_time = Fraction(wake_done[0]["time_s"]["numerator"],
                                  wake_done[0]["time_s"]["denominator"])
        reset_start = Fraction(reset["start_s"]["numerator"], reset["start_s"]["denominator"])
        reset_end = Fraction(reset["end_s"]["numerator"], reset["end_s"]["denominator"])
        release_time = Fraction(release["time_s"]["numerator"], release["time_s"]["denominator"])
        epoch_before, epoch_after = (reset_interval.get("epoch_before"),
                                     reset_interval.get("epoch_after"))
        if (sleep_time <= wake_start <= wake_done_time <= reset_start
                and reset_end <= release_time
                and reset.get("node_id") == release.get("node_id")
                and type(epoch_before) is int and type(epoch_after) is int
                and epoch_before < epoch_after
                and type(wake_done[0].get("epoch")) is int
                and wake_done[0].get("epoch") == epoch_before
                and type(release.get("epoch")) is int
                and release.get("epoch") == epoch_after):
            lifecycle = {"domain_id": domain, "sleep_node": sleep["node_id"],
                         "wake_node": wake["node_id"], "reset_node": reset["node_id"],
                         "epoch_before": epoch_before, "epoch_after": epoch_after,
                         "sleep_time_s": sleep["time_s"],
                         "wake_start_s": wake["start_s"],
                         "wake_complete_s": wake_done[0]["time_s"],
                         "reset_start_s": reset["start_s"],
                         "reset_release_s": release["time_s"]}
            break
    if lifecycle is None:
        raise EvidenceInvalid(
            "W6 requires one same-domain, timestamp-ordered sleep -> wake -> reset with an advancing epoch")
    if any(not result["complete"] for result in read_results.values()):
        raise EvidenceInvalid("W6 has an incomplete read result")

    power_events = {row["event"] for row in control_trace}
    return ExecutionClosureEvidence(FrozenMap({
        "type": "veritx/ExecutionClosureEvidence",
        "schema_version": 1,
        "profile": PROFILE,
        "status": "REFERENCE_SCENARIO_COMPLETE",
        "scope": {
            "execution": "REFERENCE_EXECUTED",
            "native_multicast": "NOT_INCLUDED_UNSUPPORTED_PRODUCER_BINDING",
            "native_rcu": "EXCLUDED_BY_OPERATOR",
            "msi_concurrency": "PARTIAL_ATOMIC_LINE_AND_CACHE_RESERVATIONS_HOSTILE_CASES_UNVERIFIED",
            "qualification": "NOT_QUALIFIED",
        },
        "design_hash": compilation.compiled_system.request.design_hash(),
        "workload_id": workload.workload_id(),
        "placement_id": placement.artifact_id(),
        "fault_profile": faults.to_dict(),
        "execution": execution,
        "assertions": {
            "per_plane_link_conservation": plane_conservation,
            "cross_plane_overlap": True,
            "shared_resource_contention": True,
            "used_endpoint_ids": sorted(used_endpoints),
            "used_endpoint_clock_rates_hz": {
                name: clock_rates[name] for name in sorted(used_clock_names)},
            "msi_read_accesses_compared": sorted(read_ids),
            "msi_write_accesses_observed": sorted(write_ids),
            "final_images_match_authored_writes": True,
            "msi_transactions_committed": len(transactions),
            "msi_final_directory_matches_committed_transitions": True,
            "msi_final_directory_lines": len(final_directory),
            "msi_owned_modified_lines": sum(
                entry["state"] == "M" for entry in final_directory.values()),
            "dag_nodes_completed_once": sorted(nodes),
            "dag_dependency_edges_verified": [list(edge) for edge in dependency_edges],
            "dag_completion_order": [
                {"node_id": node_id,
                 "time_s": {"numerator": completion_order[node_id][0].numerator,
                            "denominator": completion_order[node_id][0].denominator},
                 "ledger_index": completion_order[node_id][1]}
                for node_id in sorted(nodes)],
            "power_events_observed": sorted(power_events),
            "ordered_domain_lifecycle": lifecycle,
            "request_credit_and_fifo_drain": True,
            "loss_controls_observed": ["protocol_ack_dropped", "response_dropped"],
            "final_image_id": expected_image_id,
        },
    }))


__all__ = ["ExecutionClosureEvidence", "execute_w6_reference_scenario"]
