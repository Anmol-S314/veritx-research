"""Reference domain power-policy validation and lifecycle helpers."""
from fractions import Fraction

from veritx_dse.application.data_movement import ratio
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput, UnsupportedSemantics
from veritx_dse.model.domain_intent import PowerPolicy
from veritx_dse.simulation.clocked_fifo import edge_at_or_after


class DomainPowerRuntimeMixin:
    """Domain lifecycle methods used by the coupled reference executor."""

    def validate_power_profile(self):
        request = self.compilation.compiled_system.request
        declared = {p.id: p for p in request.power_domains}
        endpoint_rows = {row["endpoint_id"]: row
                         for row in self.compilation.compiled_system.execution_contract.endpoints}
        endpoints = {e.endpoint_id: e
                     for e in self.compilation.compiled_system.fabric.attachment.endpoints}
        self.domain_for_endpoint = {
            endpoint_id: endpoint.interface.power_domain
            for endpoint_id, endpoint in endpoints.items()}
        lifecycle_domains = {n.power_domain_id for n in self.nodes.values()
                             if n.kind in ("DOMAIN_SLEEP", "DOMAIN_WAKE", "DOMAIN_RESET")}
        collapsible_domains = {
            domain.id for domain in declared.values()
            if domain.policy is PowerPolicy.COLLAPSIBLE
            and any(endpoint.interface.power_domain == domain.id
                    for endpoint in endpoints.values())}
        if collapsible_domains != set(self.power_policies):
            raise UnsupportedSemantics(
                "every attached COLLAPSIBLE domain needs an explicit runtime policy")
        if lifecycle_domains != set(self.power_policies):
            raise UnsupportedSemantics(
                "domain power execution requires explicit policies exactly for lifecycle domains")
        if request.reset_channels and not any(
                n.kind == "DOMAIN_RESET" for n in self.nodes.values()):
            raise UnsupportedSemantics(
                "declared reset channels require an explicit DOMAIN_RESET workload node")
        if request.sideband_connections and not self.power_policies:
            raise UnsupportedSemantics("sideband intent has no bound runtime power policy")
        interfaces = {i.id: i for i in request.sideband_interfaces}
        connections = {c.connection_id: c for c in request.sideband_connections}
        reset_channels = {c.id: c for c in request.reset_channels}
        used_wake_connections = set()
        used_reset_channels = set()
        target_clocks = {}
        for domain, policy in self.power_policies.items():
            if (policy.retention_policy == "CLEAR_DOMAIN_MEMORY"
                    and self.msi_profile is not None):
                raise UnsupportedSemantics(
                    "CLEAR_DOMAIN_MEMORY with MSI dirty owners requires an explicit flush protocol")
            declaration = declared.get(domain)
            if declaration is None or declaration.policy is not PowerPolicy.COLLAPSIBLE:
                raise UnsupportedSemantics(
                    f"runtime sleep policy requires declared COLLAPSIBLE domain {domain!r}")
            if (policy.sleep_state not in declaration.declared_states
                    or policy.active_state not in declaration.declared_states):
                raise UnsupportedSemantics(
                    f"active and sleep states must both be declared for domain {domain!r}")
            members = [eid for eid, endpoint in endpoints.items()
                       if endpoint.interface.power_domain == domain]
            if not members:
                raise UnsupportedSemantics(
                    f"power domain {domain!r} has no attached fabric endpoints")
            clocks = {endpoint_rows[eid]["transaction_clock_domain"]
                      for eid in members}
            if len(clocks) != 1:
                raise UnsupportedSemantics(
                    "domain lifecycle requires one explicit transaction clock per power domain")
            target_clock = next(iter(clocks))
            if target_clock not in self.clocks or policy.control_clock not in self.clocks:
                raise InvalidInput("power control and target clocks must be compiled")
            target_clocks[domain] = target_clock
            connection = connections.get(policy.wake_connection_id)
            if connection is None:
                raise UnsupportedSemantics(
                    f"wake path {policy.wake_connection_id!r} is not a declared sideband connection")
            source = interfaces.get(connection.source.sideband_id)
            destination = interfaces.get(connection.destination.sideband_id)
            if (source is None or destination is None
                    or source.kind.value != "interrupt"
                    or source.direction.value != "output"
                    or destination.kind.value != "interrupt"
                    or destination.direction.value != "input"):
                raise UnsupportedSemantics(
                    "wake path must be a declared INTERRUPT output-to-input connection")
            if (source.power_domain not in declared
                    or destination.power_domain not in declared
                    or declared[source.power_domain].policy is not PowerPolicy.ALWAYS_ON
                    or declared[destination.power_domain].policy is not PowerPolicy.ALWAYS_ON):
                raise UnsupportedSemantics(
                    "interrupt wake route must terminate in an active declared ALWAYS_ON control domain")
            if (source.clock_domain != policy.control_clock
                    or destination.clock_domain != policy.control_clock):
                raise UnsupportedSemantics(
                    "interrupt wake path must use the authored active control clock without an undeclared CDC")
            used_wake_connections.add(policy.wake_connection_id)
        if set(connections) != used_wake_connections:
            raise UnsupportedSemantics(
                "this power profile refuses sideband connections not bound as a domain interrupt wake path")
        if set(interfaces) != {ref.sideband_id for connection in connections.values()
                              for ref in (connection.source, connection.destination)}:
            raise UnsupportedSemantics(
                "this power profile refuses unused sideband interfaces")
        self.domain_target_clock = target_clocks
        domain_access_nodes = {domain: set() for domain in self.power_policies}
        tensor_by_id = {t.tensor_id: t for t in self.workload.demand.tensors}
        for access in self.accesses.values():
            node = self.access_nodes[access.access_id]
            domains = {self.domain_for_endpoint.get(access.issuer)}
            domains.update(self.domain_for_endpoint.get(shard.target)
                           for shard in tensor_by_id[access.tensor_id].shards)
            for domain in domain_access_nodes:
                if domain in domains:
                    domain_access_nodes[domain].add(node)
        for node in self.nodes.values():
            if node.kind != "DOMAIN_RESET":
                continue
            channel = reset_channels.get(node.reset_channel_id)
            if channel is None:
                raise UnsupportedSemantics(
                    f"domain reset channel {node.reset_channel_id!r} is not declared")
            domain = node.power_domain_id
            if channel.target_clock_domain != target_clocks[domain]:
                raise UnsupportedSemantics(
                    "domain reset channel must target the domain's unique transaction clock")
            if channel.deassertion.value != "SYNC" or channel.synchronizer_stages is None:
                raise UnsupportedSemantics(
                    "domain reset execution requires an explicitly sized synchronous release synchronizer")
            for dependency_channel in channel.depends_on:
                prior_nodes = [reset.node_id for reset in self.nodes.values()
                               if reset.kind == "DOMAIN_RESET"
                               and reset.reset_channel_id == dependency_channel]
                if not any(prior in self.deps[node.node_id] for prior in prior_nodes):
                    raise UnsupportedSemantics(
                        f"reset {channel.id!r} dependency {dependency_channel!r} "
                        "must complete before this domain reset")
            sleep_node = next(n.node_id for n in self.nodes.values()
                              if n.kind == "DOMAIN_SLEEP"
                              and n.power_domain_id == domain)
            wake_node = next(n.node_id for n in self.nodes.values()
                             if n.kind == "DOMAIN_WAKE"
                             and n.power_domain_id == domain)
            if not ((sleep_node in self.deps[node.node_id]
                     or node.node_id in self.deps[sleep_node])
                    and (wake_node in self.deps[node.node_id]
                         or node.node_id in self.deps[wake_node])):
                raise UnsupportedSemantics(
                    "domain reset must be ordered before sleep or after wake")
            used_reset_channels.add(node.reset_channel_id)
            for access_node in domain_access_nodes[domain]:
                if (node.node_id not in self.deps[access_node]
                        and access_node not in self.deps[node.node_id]):
                    raise UnsupportedSemantics(
                        "domain reset must be dependency-ordered against every access that can touch its endpoints")
        if set(reset_channels) != used_reset_channels:
            raise UnsupportedSemantics(
                "reset channels must be bound to DOMAIN_RESET nodes; global DRAIN_RESET remains separate")
        for node in self.nodes.values():
            if node.kind == "DOMAIN_WAKE":
                sleeps = [candidate.node_id for candidate in self.nodes.values()
                          if candidate.kind == "DOMAIN_SLEEP"
                          and candidate.power_domain_id == node.power_domain_id]
                if not any(sleep in self.deps[node.node_id] for sleep in sleeps):
                    raise InvalidInput("DOMAIN_WAKE must depend on a prior DOMAIN_SLEEP for the same domain")

    def _domain_children(self, domain):
        return self.active_domain_transactions[domain]

    def _apply_domain_retention(self, domain, node_id, now, event):
        policy = self.power_policies[domain]
        if policy.retention_policy == "RETAIN_ALL":
            cleared = 0
        else:
            if self.msi_profile is not None:
                raise EvidenceInvalid(
                    "MSI dirty-state clear passed policy validation unexpectedly")
            cleared = 0
            for tensor in self.workload.demand.tensors:
                for shard in tensor.shards:
                    if self.domain_for_endpoint.get(shard.target) != domain:
                        continue
                    start, end = shard.offset_bytes, shard.offset_bytes + shard.size_bytes
                    self.images[tensor.tensor_id][start:end] = bytes(shard.size_bytes)
                    self.logical_images[tensor.tensor_id][start:end] = bytes(shard.size_bytes)
                    cleared += shard.size_bytes
                    self.cache_lines.get(shard.target, {}).clear()
                    self.cache_projection.get(shard.target, {}).clear()
            if not cleared:
                raise UnsupportedSemantics(
                    f"CLEAR_DOMAIN_MEMORY found no authored home shards in domain {domain!r}")
        self.power_control_trace.append({
            "event": "domain_retention_applied", "lifecycle_event": event,
            "node_id": node_id, "domain_id": domain,
            "retention_policy": policy.retention_policy,
            "bytes_cleared": cleared, "time_s": ratio(now)})
        return cleared

    def _reserve_control(self, key, *, now, cycles, clock, owner):
        period = Fraction(1, self.clocks[clock])
        start = edge_at_or_after(max(now, self.lane_free.free_at(key)), period)
        end = start + cycles * period
        self.lane_free.reserve(key, arrival=now, start=start, end=end,
                               free_at=end, owner=owner)
        return start, end

    def _start_domain_sleep(self, domain, node_id, now):
        if self.domain_states[domain] != "DRAINING" or self._domain_children(domain):
            return
        policy = self.power_policies[domain]
        owner = f"power:{domain}:{node_id}"
        start, end = self._reserve_control(
            ("domain-power", domain), now=now,
            cycles=policy.isolation_cycles, clock=policy.control_clock,
            owner=owner)
        self.domain_states[domain] = "ISOLATING"
        self.power_control_trace.append({"event": "isolation_assert",
            "node_id": node_id, "domain_id": domain,
            "start_s": ratio(start), "end_s": ratio(end),
            "retention_policy": policy.retention_policy})
        self.push(end, 0, ("runtime", ("domain_isolation_complete", domain, node_id)))


