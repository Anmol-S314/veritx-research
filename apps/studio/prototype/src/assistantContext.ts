import type { LoadedProject, LoadedRun } from './project';
import type { SimLoad, SimSeries, Topology, TrafficMatrix } from './gateway';
import { buildChannelIndex, channelMatchLabel, matchMeasuredChannel } from './channelTopology';
import { channelCosts, median } from './channelAnalysis';
import type { ContextPick } from './contextSelection';

export type AssistantScopeInput = {
  route: string;
  page: { title: string; group: string } | null;
  project?: LoadedProject | null;
  run?: LoadedRun | null;
  topology?: Topology | null;
  load?: SimLoad | null;
  series?: SimSeries | null;
  portWires?: Map<string, { wire: number; taps: number[] }>;
  picks: ContextPick[];
  includeDraft?: boolean;
};

export type ContextPacket = {
  schema: 'srota-studio/assistant-context/v1';
  scope: {
    route: string;
    page: string;
    group: string;
    project: { id: string; name: string } | null;
    revision: string | null;
    run: { id: string; revision_id: string; backend: string | null; qualification: string | null; status: string | null } | null;
    topology: { family: string; routers: number; channels: number; endpoints: number; shared_wires: number } | null;
  };
  measured: {
    availability: 'measured channel counters' | 'not loaded' | 'run has no channel rows';
    channels: number;
    active_channels: number;
    total_flits: number;
    link_capacity_flits_per_cycle: number | null;
    windows: number | null;
    cycles_sampled: number | null;
    series_loaded: boolean;
  } | null;
  selections: Record<string, unknown>[];
  derived: string[];
  gaps: string[];
  draft?: unknown;
};

export type LocalAnswer = {
  paragraphs: string[];
  evidence: { label: string; value: string }[];
  caveats: string[];
};

type RouterRoute = {
  key: string;
  label: string;
  direction: string | null;
  neighbour: number | null;
  local: boolean;
  wire_id: number | null;
  unmatched: boolean;
  flits: number;
  channels: number;
  queue_cycles: number;
  peak_utilization: number;
  top_channel_id: number | null;
};

export type RouterTraffic = {
  router: number;
  measured: boolean;
  channels: number;
  active_channels: number;
  egress_flits: number;
  ingress_flits: number;
  local_flits: number;
  declared_link_flits: number;
  shared_wire_flits: number;
  unmatched_flits: number;
  queue_cycles: number;
  arb_cycles: number;
  mean_utilization: number;
  peak_utilization: number;
  weighted_hop_latency: number | null;
  routes: RouterRoute[];
  top_channels: {
    id: number;
    flits: number;
    utilization: number;
    queue_per_flit: number | null;
    peak_utilization: number;
    label: string;
  }[];
  declared: {
    coordinates: number[] | null;
    seat_capacity: number | null;
    outbound_channels: number;
    inbound_channels: number;
    shared_wire_drivers: number;
    attached_endpoints: number;
    neighbours: number[];
    endpoint_ids: number[];
  };
  gap: string | null;
};

const numberOrNull = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const pct = (value: number, total: number): string => total > 0 ? `${(100 * value / total).toFixed(1)} %` : '—';

/** The measured router view: source-port counters grouped by the declared
 *  destination they joined. No router-internal occupancy is inferred. */
export function routerTraffic(topology: Topology | null, channels: SimLoad['channels'] | null | undefined, router: number, portWires?: Map<string, { wire: number; taps: number[] }>): RouterTraffic {
  const index = buildChannelIndex(topology, portWires);
  const routes = new Map<string, RouterRoute>();
  const top = new Map<number, RouterTraffic['top_channels'][number]>();
  let egress = 0, ingress = 0, local = 0, declared = 0, wireFlits = 0, unmatched = 0;
  let queue = 0, arb = 0, utilizationSum = 0, measuredRows = 0, active = 0, peak = 0;
  let latencyWeight = 0, latencyTotal = 0;
  for (const channel of channels ?? []) {
    const match = matchMeasuredChannel(index, Number(channel.logical_channel_id));
    if (!match) continue;
    if (match.channel?.dst_router === router) ingress += channel.flits_total;
    if (match.measured.router !== router) continue;
    egress += channel.flits_total;
    measuredRows += 1;
    if (channel.flits_total > 0) active += 1;
    utilizationSum += channel.utilization;
    peak = Math.max(peak, channel.peak_window_utilization);
    queue += channel.queue_cycles_total ?? 0;
    arb += channel.arb_wait_cycles_total ?? 0;
    if (typeof channel.per_hop_latency_mean_cycles === 'number' && channel.flits_total > 0) {
      latencyWeight += channel.flits_total;
      latencyTotal += channel.per_hop_latency_mean_cycles * channel.flits_total;
    }
    if (match.local) local += channel.flits_total;
    else if (match.wire) wireFlits += channel.flits_total;
    else if (match.channel) declared += channel.flits_total;
    else unmatched += channel.flits_total;
    const key = match.local ? 'local' : match.wire ? `wire:${match.wire.id}` : match.channel ? `to:${match.channel.dst_router}` : 'unmatched';
    const label = match.local ? 'Local eject'
      : match.wire ? `Wire W${match.wire.id} · driver`
      : match.channel ? `R${router} → R${match.channel.dst_router}${match.direction ? ` · ${match.direction}` : ''}`
      : 'No declared link';
    const route = routes.get(key) ?? {
      key, label, direction: match.direction, neighbour: match.channel?.dst_router ?? match.neighbour,
      local: match.local, wire_id: match.wire?.id ?? null, unmatched: match.unmatched,
      flits: 0, channels: 0, queue_cycles: 0, peak_utilization: 0, top_channel_id: null,
    };
    route.flits += channel.flits_total;
    route.channels += 1;
    route.queue_cycles += channel.queue_cycles_total ?? 0;
    route.peak_utilization = Math.max(route.peak_utilization, channel.peak_window_utilization);
    if (route.top_channel_id === null || channel.flits_total > (top.get(route.top_channel_id)?.flits ?? -1)) route.top_channel_id = Number(channel.logical_channel_id);
    routes.set(key, route);
    const cost = channelCosts([channel])[0];
    top.set(Number(channel.logical_channel_id), {
      id: Number(channel.logical_channel_id),
      flits: channel.flits_total,
      utilization: channel.utilization,
      queue_per_flit: cost?.queuePerFlit ?? null,
      peak_utilization: channel.peak_window_utilization,
      label: channelMatchLabel(match),
    });
  }
  const declaredOut = (topology?.channels ?? []).filter(channel => channel.src_router === router);
  const declaredIn = (topology?.channels ?? []).filter(channel => channel.dst_router === router);
  const attached = (topology?.endpoints ?? []).filter(endpoint => endpoint.router_id === router);
  const sharedDrivers = (topology?.shared_links ?? []).filter(link => link.src_router === router);
  const route = topology?.routers.find(item => item.router_id === router) ?? null;
  const measured = channels != null;
  return {
    router,
    measured,
    channels: measuredRows,
    active_channels: active,
    egress_flits: egress,
    ingress_flits: ingress,
    local_flits: local,
    declared_link_flits: declared,
    shared_wire_flits: wireFlits,
    unmatched_flits: unmatched,
    queue_cycles: queue,
    arb_cycles: arb,
    mean_utilization: measuredRows ? utilizationSum / measuredRows : 0,
    peak_utilization: peak,
    weighted_hop_latency: latencyWeight ? latencyTotal / latencyWeight : null,
    routes: [...routes.values()].filter(route => route.flits > 0).sort((a, b) => b.flits - a.flits).slice(0, 8),
    top_channels: [...top.values()].filter(channel => channel.flits > 0).sort((a, b) => b.flits - a.flits).slice(0, 8),
    declared: {
      coordinates: Array.isArray(route?.coordinates) ? route.coordinates.map(Number) : null,
      seat_capacity: route?.seat_capacity ?? null,
      outbound_channels: declaredOut.length,
      inbound_channels: declaredIn.length,
      shared_wire_drivers: sharedDrivers.length,
      attached_endpoints: attached.length,
      neighbours: [...new Set(declaredOut.map(channel => channel.dst_router))].sort((a, b) => a - b),
      endpoint_ids: attached.map(endpoint => endpoint.endpoint_id),
    },
    gap: measured ? null : 'No sampled channel counters are loaded for this run.',
  };
}

export type ChannelFacts = {
  id: string;
  label: string;
  measured: boolean;
  resource: string;
  declared: {
    src_router: number; src_port: number; dst_router: number; dst_port: number;
    width_bits: number; latency_cycles: number;
  } | null;
  counters: {
    flits: number; utilization: number; peak_utilization: number; queue_cycles: number;
    arb_wait_cycles: number; mean_hop_latency: number | null; peak_hop_latency: number | null;
    peak_queued_flits: number | null; stalls: boolean;
  } | null;
  derived: {
    queue_per_flit: number | null;
    tail_ratio: number | null;
  };
};

export function channelFacts(topology: Topology | null, channels: SimLoad['channels'] | null | undefined, id: string, portWires?: Map<string, { wire: number; taps: number[] }>): ChannelFacts {
  const index = buildChannelIndex(topology, portWires);
  const row = (channels ?? []).find(channel => String(channel.logical_channel_id) === String(id)) ?? null;
  const match = row ? matchMeasuredChannel(index, Number(row.logical_channel_id)) : null;
  const channel = match?.channel ?? (topology?.channels ?? []).find(item => String(item.channel_id) === String(id)) ?? null;
  const cost = row ? channelCosts([row])[0] : null;
  return {
    id: String(id),
    label: `Channel CH-${id}`,
    measured: row != null,
    resource: row ? channelMatchLabel(match) : channel ? `R${channel.src_router}:${channel.src_port} → R${channel.dst_router}:${channel.dst_port}` : 'No declared channel',
    declared: channel ? {
      src_router: channel.src_router, src_port: channel.src_port, dst_router: channel.dst_router, dst_port: channel.dst_port,
      width_bits: channel.width_bits, latency_cycles: channel.latency_cycles,
    } : null,
    counters: row ? {
      flits: row.flits_total,
      utilization: row.utilization,
      peak_utilization: row.peak_window_utilization,
      queue_cycles: row.queue_cycles_total ?? 0,
      arb_wait_cycles: row.arb_wait_cycles_total ?? 0,
      mean_hop_latency: numberOrNull(row.per_hop_latency_mean_cycles),
      peak_hop_latency: numberOrNull(row.peak_per_hop_latency_cycles),
      peak_queued_flits: numberOrNull(row.peak_queued_flits),
      stalls: Boolean(row.has_stalls),
    } : null,
    derived: {
      queue_per_flit: cost?.queuePerFlit ?? null,
      tail_ratio: cost?.tailRatio ?? null,
    },
  };
}

export type WireFacts = {
  id: number;
  driver: number | null;
  taps: number[];
  width_bits: number | null;
  latency_cycles: number | null;
  measured: boolean;
  measured_flits: number;
  measured_channels: number;
};

export function wireFacts(topology: Topology | null, channels: SimLoad['channels'] | null | undefined, id: string, portWires?: Map<string, { wire: number; taps: number[] }>): WireFacts {
  const wire = (topology?.shared_links ?? []).find(link => String(link.shared_link_id) === String(id)) ?? null;
  const index = buildChannelIndex(topology, portWires);
  let flits = 0, count = 0;
  for (const channel of channels ?? []) {
    const match = matchMeasuredChannel(index, Number(channel.logical_channel_id));
    if (match?.wire?.id === wire?.shared_link_id) { flits += channel.flits_total; count += 1; }
  }
  return {
    id: wire?.shared_link_id ?? Number(id),
    driver: wire?.src_router ?? null,
    taps: wire?.taps ?? [],
    width_bits: wire?.width_bits ?? null,
    latency_cycles: wire?.latency_cycles ?? null,
    measured: channels != null,
    measured_flits: flits,
    measured_channels: count,
  };
}

export type EndpointFacts = {
  id: number;
  kind: string | null;
  router: number | null;
  port: number | null;
  seat_capacity: number | null;
  attached_endpoints: number;
  measured_router_traffic: RouterTraffic | null;
  pairs: { src: number; dst: number; packets: number; flits: number }[];
};

export function endpointFacts(topology: Topology | null, channels: SimLoad['channels'] | null | undefined, matrix: TrafficMatrix | null | undefined, id: string, portWires?: Map<string, { wire: number; taps: number[] }>): EndpointFacts {
  const endpoint = (topology?.endpoints ?? []).find(item => String(item.endpoint_id) === String(id)) ?? null;
  const router = endpoint?.router_id ?? null;
  const routerRow = (topology?.routers ?? []).find(item => item.router_id === router) ?? null;
  const pairs = (matrix?.pairs ?? []).filter(pair => pair.src === Number(id) || pair.dst === Number(id));
  return {
    id: endpoint?.endpoint_id ?? Number(id),
    kind: endpoint?.kind ?? null,
    router,
    port: endpoint?.port_id ?? null,
    seat_capacity: routerRow?.seat_capacity ?? null,
    attached_endpoints: router === null ? 0 : (topology?.endpoints ?? []).filter(item => item.router_id === router).length,
    measured_router_traffic: router === null ? null : routerTraffic(topology, channels, router, portWires),
    pairs: pairs.slice(0, 8),
  };
}

export type PairFacts = {
  pair: string;
  packets: number;
  flits: number;
  share_of_flits: number | null;
  found: boolean;
};

export function pairFacts(matrix: TrafficMatrix | null | undefined, id: string): PairFacts {
  const [src, dst] = id.split(':').map(Number);
  const pair = (matrix?.pairs ?? []).find(item => item.src === src && item.dst === dst) ?? null;
  const total = matrix?.flits ?? (matrix?.pairs ?? []).reduce((sum, item) => sum + item.flits, 0);
  return {
    pair: `${src} → ${dst}`,
    packets: pair?.packets ?? 0,
    flits: pair?.flits ?? 0,
    share_of_flits: pair && total > 0 ? pair.flits / total : null,
    found: pair != null,
  };
}

function selectionContext(pick: ContextPick, input: AssistantScopeInput): Record<string, unknown> {
  const { topology, load, run } = input;
  if (pick.kind === 'router') return { ...pick, resolved: routerTraffic(topology ?? null, load?.channels ?? null, Number(pick.id), input.portWires) };
  if (pick.kind === 'channel' || pick.kind === 'declared-channel') return { ...pick, resolved: channelFacts(topology ?? null, pick.kind === 'channel' ? load?.channels ?? null : null, pick.id, input.portWires) };
  if (pick.kind === 'wire') return { ...pick, resolved: wireFacts(topology ?? null, load?.channels ?? null, pick.id, input.portWires) };
  if (pick.kind === 'endpoint') return { ...pick, resolved: endpointFacts(topology ?? null, load?.channels ?? null, run?.matrix ?? null, pick.id, input.portWires) };
  if (pick.kind === 'pair') return { ...pick, resolved: pairFacts(run?.matrix ?? null, pick.id) };
  return { ...pick };
}

export function buildContextPacket(input: AssistantScopeInput): ContextPacket {
  const channels = input.load?.channels ?? null;
  const active = (channels ?? []).filter(channel => channel.flits_total > 0);
  const totalFlits = (channels ?? []).reduce((sum, channel) => sum + channel.flits_total, 0);
  const gaps = new Set<string>([
    'packet-latency percentiles and histograms',
    'unique packets per channel',
    'per-initiator or per-packet observed paths',
    'router-internal queue occupancy',
    'hardware timing, power, area and qualification',
  ]);
  if (!input.run) gaps.add('no evaluation run is selected');
  if (!input.topology) gaps.add('no revision topology is loaded');
  if (input.load == null) gaps.add('no sampled channel counters are loaded for this run');
  else if (channels && channels.length === 0) gaps.add('the sampled series has no channel rows');
  if (!input.run?.matrix) gaps.add('no endpoint-pair traffic matrix is loaded');
  return {
    schema: 'srota-studio/assistant-context/v1',
    scope: {
      route: input.route,
      page: input.page?.title ?? 'Current view',
      group: input.page?.group ?? '',
      project: input.project ? { id: input.project.detail.project.project_id, name: input.project.detail.project.name } : null,
      revision: input.project?.detail.active_revision_id ?? input.run?.detail.revision_id ?? null,
      run: input.run ? {
        id: input.run.detail.run_id,
        revision_id: input.run.detail.revision_id,
        backend: input.run.detail.backend ?? null,
        qualification: input.run.detail.qualification ?? null,
        status: input.run.detail.status ?? null,
      } : null,
      topology: input.topology ? {
        family: input.topology.family,
        routers: input.topology.counts?.routers ?? input.topology.routers.length,
        channels: input.topology.counts?.channels ?? input.topology.channels.length,
        endpoints: input.topology.counts?.endpoints ?? input.topology.endpoints.length,
        shared_wires: input.topology.counts?.shared_links ?? input.topology.shared_links?.length ?? 0,
      } : null,
    },
    measured: input.load == null ? null : {
      availability: channels && channels.length === 0 ? 'run has no channel rows' : 'measured channel counters',
      channels: channels?.length ?? 0,
      active_channels: active.length,
      total_flits: totalFlits,
      link_capacity_flits_per_cycle: input.load.link_capacity_flits_per_cycle ?? null,
      windows: input.load.num_windows ?? null,
      cycles_sampled: input.load.cycles_sampled ?? null,
      series_loaded: input.series != null,
    },
    selections: input.picks.map(pick => selectionContext(pick, input)),
    derived: [
      'source-router grouping of measured channel counters',
      'per-channel queue cycles per delivered flit',
      'per-channel latency peak ÷ mean tail ratio',
      'network median queue cost',
    ],
    gaps: [...gaps],
    draft: input.includeDraft && input.project?.request ? input.project.request : undefined,
  };
}

const flow = (value: number): string => value.toLocaleString();
const cyc = (value: number | null): string => value == null ? 'not recorded' : `${value.toFixed(2)} cyc`;

function routerAnswer(selection: Record<string, unknown>, question: string, packet: ContextPacket): LocalAnswer | null {
  const traffic = selection.resolved as RouterTraffic | undefined;
  if (!traffic || typeof traffic.router !== 'number') return null;
  const q = question.toLowerCase();
  const wantsMissing = /(missing|not recorded|not present|gap|limitation|evidence)/.test(q);
  if (wantsMissing) return null;
  const run = packet.scope.run;
  if (!traffic.measured) {
    const declared = traffic.declared;
    return {
      paragraphs: [
        `R${traffic.router} is attached, but there are no sampled channel counters in this context, so no measured egress or ingress number exists for it.`,
        `Declared connectivity only: ${declared.outbound_channels} outbound and ${declared.inbound_channels} inbound directed channels${declared.shared_wire_drivers ? `, ${declared.shared_wire_drivers} shared-wire driver${declared.shared_wire_drivers === 1 ? '' : 's'}` : ''}, and ${declared.attached_endpoints} attached endpoint${declared.attached_endpoints === 1 ? '' : 's'}${declared.neighbours.length ? ` (neighbours ${declared.neighbours.map(id => `R${id}`).join(', ')})` : ''}. That is fabric structure, not observed traffic.`,
      ],
      evidence: [
        { label: 'Outbound channels', value: String(declared.outbound_channels) },
        { label: 'Inbound channels', value: String(declared.inbound_channels) },
        { label: 'Attached endpoints', value: String(declared.attached_endpoints) },
      ],
      caveats: ['No number is substituted when the run did not record sampled channel counters.'],
    };
  }
  const wantedCost = /(cost|queue|latenc|stall|busy|util|hot|congest|why)/.test(q);
  const total = traffic.egress_flits;
  const top = traffic.routes.slice(0, 3);
  const breakdown = top.map(route => `${route.label}: ${flow(route.flits)} flits (${pct(route.flits, total)})`).join('; ');
  if (total === 0) {
    return {
      paragraphs: [
        `R${traffic.router} has no measured egress in ${run ? run.id : 'the attached run'}: ${traffic.channels} sampled source-port row${traffic.channels === 1 ? '' : 's'} exist for it, but every one reports zero flits. ${traffic.ingress_flits ? `Channels into R${traffic.router} carried ${flow(traffic.ingress_flits)} measured flits from declared neighbours.` : 'No measured ingress was attributable to declared neighbours either.'}`,
        traffic.declared.outbound_channels
          ? `The revision still declares ${traffic.declared.outbound_channels} outbound directed channel${traffic.declared.outbound_channels === 1 ? '' : 's'}${traffic.declared.neighbours.length ? ` to ${traffic.declared.neighbours.map(id => `R${id}`).join(', ')}` : ''}. A recorded zero in this run is not a missing row and not a statement about another run.`
          : 'The revision declares no outbound channels for this router.',
      ],
      evidence: [
        { label: 'Egress flits', value: '0' },
        { label: 'Sampled rows', value: String(traffic.channels) },
        { label: 'Ingress flits', value: traffic.ingress_flits ? flow(traffic.ingress_flits) : '0' },
      ],
      caveats: ['This is a measured zero for the attached sampled series. It is not a hardware-idle proof, and it does not generalize to other runs or workloads.'],
    };
  }
  const paragraphs = [
    `R${traffic.router} has ${flow(total)} measured flits on its outgoing channels${run ? ` in ${run.id}` : ''} across ${traffic.active_channels} active source-port channel${traffic.active_channels === 1 ? '' : 's'}. ${traffic.local_flits ? `Local ejection accounts for ${flow(traffic.local_flits)} flits; ` : ''}${traffic.ingress_flits ? `channels into R${traffic.router} carried ${flow(traffic.ingress_flits)} measured flits from declared neighbours.` : 'No measured ingress was attributable to declared neighbours.'}`,
  ];
  if (breakdown) paragraphs.push(`Where it went: ${breakdown}${traffic.unmatched_flits ? `; ${flow(traffic.unmatched_flits)} flits could not be joined to a declared link.` : '.'}`);
  const costliest = [...traffic.top_channels].filter(channel => channel.queue_per_flit != null).sort((a, b) => (b.queue_per_flit ?? 0) - (a.queue_per_flit ?? 0))[0];
  if (wantedCost) {
    paragraphs.push(costliest
      ? `Its highest queue cost is CH-${costliest.id}: ${costliest.queue_per_flit?.toFixed(2)} queue cycles per delivered flit, ${costliest.peak_utilization ? `with ${(100 * costliest.peak_utilization).toFixed(1)} % peak window utilization.` : 'with no peak-window utilization reported.'}`
      : 'This run records no queue-cost quotient for the selected router, so no congestion ranking is derived.');
  } else if (costliest) {
    paragraphs.push(`The costliest outgoing channel in the attached counters is CH-${costliest.id} at ${costliest.queue_per_flit?.toFixed(2)} queue cycles per delivered flit.`);
  }
  const evidence = [
    { label: 'Egress flits', value: flow(total) },
    { label: 'Ingress flits', value: traffic.ingress_flits ? flow(traffic.ingress_flits) : 'not attributable' },
    { label: 'Local eject', value: flow(traffic.local_flits) },
    { label: 'Queue cycles', value: flow(traffic.queue_cycles) },
    { label: 'Peak util.', value: `${(100 * traffic.peak_utilization).toFixed(1)} %` },
  ];
  if (traffic.weighted_hop_latency != null) evidence.push({ label: 'Mean hop latency', value: cyc(traffic.weighted_hop_latency) });
  return {
    paragraphs,
    evidence,
    caveats: [
      'These are sampled channel counters grouped by source port, not router-internal occupancy, per-initiator traffic, unique packets, or a causal diagnosis.',
      wantedCost ? 'High per-flit cost is not by itself a congestion verdict; no arbitration trace or packet path is attached.' : 'A missing counter stays unavailable rather than becoming zero.',
    ],
  };
}

function channelAnswer(selection: Record<string, unknown>, question: string): LocalAnswer | null {
  const facts = selection.resolved as ChannelFacts | undefined;
  if (!facts || !facts.id) return null;
  const q = question.toLowerCase();
  if (/(missing|not recorded|gap|limitation)/.test(q)) return null;
  if (!facts.counters) {
    return {
      paragraphs: [
        `CH-${facts.id} is attached, but this context has no measured counter row for it.`,
        facts.declared ? `The declared resource is R${facts.declared.src_router}:${facts.declared.src_port} → R${facts.declared.dst_router}:${facts.declared.dst_port}, ${facts.declared.width_bits} bits, ${facts.declared.latency_cycles} cycles. That is declared connectivity, not observed traffic.` : 'No declared channel matches this id either, so no resource is inferred.',
      ],
      evidence: facts.declared ? [
        { label: 'Declared link', value: `R${facts.declared.src_router} → R${facts.declared.dst_router}` },
        { label: 'Width', value: `${facts.declared.width_bits} bits` },
        { label: 'Latency', value: `${facts.declared.latency_cycles} cyc` },
      ] : [],
      caveats: ['No sampled counter is substituted for a missing measurement.'],
    };
  }
  const cost = facts.derived.queue_per_flit;
  const tail = facts.derived.tail_ratio;
  const paragraphs = [
    `CH-${facts.id} carried ${flow(facts.counters.flits)} measured flits at ${(100 * facts.counters.utilization).toFixed(1)} % sustained utilization and ${(100 * facts.counters.peak_utilization).toFixed(1)} % peak window utilization. ${facts.resource}.`,
    cost == null
      ? 'This row has no queue-cycle counter, so queue cost per flit stays unavailable.'
      : `It spent ${flow(facts.counters.queue_cycles)} queue cycles and ${flow(facts.counters.arb_wait_cycles)} arbitration-wait cycles, which is ${cost.toFixed(2)} queue cycles per delivered flit.`,
  ];
  if (facts.counters.mean_hop_latency != null) paragraphs.push(`The measured mean per-hop latency is ${cyc(facts.counters.mean_hop_latency)}${facts.counters.peak_hop_latency != null ? `, with a peak of ${cyc(facts.counters.peak_hop_latency)}` : ''}.`);
  if (tail != null) paragraphs.push(`Peak ÷ mean tail ratio: ${tail.toFixed(1)}×.`);
  return {
    paragraphs,
    evidence: [
      { label: 'Flits', value: flow(facts.counters.flits) },
      { label: 'Utilization', value: `${(100 * facts.counters.utilization).toFixed(1)} %` },
      { label: 'Peak util.', value: `${(100 * facts.counters.peak_utilization).toFixed(1)} %` },
      { label: 'Queue / flit', value: cost == null ? 'not recorded' : `${cost.toFixed(2)} cyc` },
      ...(tail == null ? [] : [{ label: 'Tail ratio', value: `${tail.toFixed(1)}×` }]),
    ],
    caveats: [
      'Measured channel counters and derived quotients only. This is not a packet-latency percentile, a unique-packet count, or a congestion verdict.',
      /why|cause|congest/.test(q) ? 'The context has no observed packet path or arbitration trace, so it cannot establish cause.' : 'A zero or unavailable value is never filled by inference.',
    ],
  };
}

function wireAnswer(selection: Record<string, unknown>): LocalAnswer | null {
  const wire = selection.resolved as WireFacts | undefined;
  if (!wire || typeof wire.id !== 'number') return null;
  return {
    paragraphs: [
      `W${wire.id} is a declared multidrop wire: driver R${wire.driver ?? '?'} → taps ${wire.taps.length ? wire.taps.map(tap => `R${tap}`).join(', ') : 'none'}, ${wire.width_bits ?? '?'} bits, ${wire.latency_cycles ?? '?'} cycles.`,
      wire.measured
        ? `${flow(wire.measured_flits)} measured flits were joined to this wire across ${wire.measured_channels} measured channel row${wire.measured_channels === 1 ? '' : 's'}. Wire egress is counted at the driver; per-tap landing is not implied by that counter.`
        : 'No sampled counters are attached, so only the declared structure is available.',
    ],
    evidence: [
      { label: 'Driver', value: `R${wire.driver ?? '?'}` },
      { label: 'Taps', value: String(wire.taps.length) },
      { label: 'Width', value: wire.width_bits == null ? 'not declared' : `${wire.width_bits} bits` },
      ...(wire.measured ? [{ label: 'Measured flits', value: flow(wire.measured_flits) }] : []),
    ],
    caveats: ['A shared wire is one driver with many taps, not a set of point-to-point channels. Measured ingress at individual taps is not inferred.'],
  };
}

function endpointAnswer(selection: Record<string, unknown>): LocalAnswer | null {
  const endpoint = selection.resolved as EndpointFacts | undefined;
  if (!endpoint || typeof endpoint.id !== 'number') return null;
  const traffic = endpoint.measured_router_traffic;
  const pairText = endpoint.pairs.length
    ? `Endpoint-pair counts touching this endpoint: ${endpoint.pairs.map(pair => `${pair.src} → ${pair.dst}: ${flow(pair.flits)} flits`).join('; ')}.`
    : 'No endpoint-pair rows touching this endpoint are attached.';
  return {
    paragraphs: [
      `EP-${endpoint.id} is a declared ${endpoint.kind ?? 'endpoint'} attached to R${endpoint.router ?? '?'} port ${endpoint.port ?? '?'}.`,
      traffic?.measured
        ? `At its router, outgoing channels carried ${flow(traffic.egress_flits)} measured flits and ${flow(traffic.local_flits)} of those were local ejections. This is router/source-port traffic, not a per-endpoint flow.`
        : 'No sampled router counters are attached, so no measured traffic is available for its attachment.',
      pairText,
    ],
    evidence: [
      { label: 'Kind', value: endpoint.kind ?? 'not declared' },
      { label: 'Router', value: `R${endpoint.router ?? '?'}` },
      { label: 'Port', value: String(endpoint.port ?? '?') },
      ...(traffic?.measured ? [{ label: 'Router egress', value: flow(traffic.egress_flits) }] : []),
    ],
    caveats: ['Attachment and endpoint-pair counts are different scopes. No per-initiator latency or observed packet path is invented.'],
  };
}

function pairAnswer(selection: Record<string, unknown>): LocalAnswer | null {
  const pair = selection.resolved as PairFacts | undefined;
  if (!pair || !pair.pair) return null;
  if (!pair.found) {
    return {
      paragraphs: [`No measured endpoint-pair row exists for ${pair.pair} in the attached matrix. The pair is not assigned an inferred zero.`],
      evidence: [],
      caveats: ['A missing pair row is unavailable, not evidence of zero traffic.'],
    };
  }
  return {
    paragraphs: [
      `Endpoint pair ${pair.pair} carried ${flow(pair.packets)} packets and ${flow(pair.flits)} measured flits${pair.share_of_flits == null ? '' : `, ${(100 * pair.share_of_flits).toFixed(2)} % of the matrix flit total`}.`,
    ],
    evidence: [
      { label: 'Packets', value: flow(pair.packets) },
      { label: 'Flits', value: flow(pair.flits) },
      ...(pair.share_of_flits == null ? [] : [{ label: 'Share', value: `${(100 * pair.share_of_flits).toFixed(2)} %` }]),
    ],
    caveats: ['This is a requested/injected trace-pair count; it is not an observed packet path, per-link counter, or latency distribution.'],
  };
}

function missingAnswer(packet: ContextPacket): LocalAnswer {
  const measured = packet.measured;
  return {
    paragraphs: [
      `This context can see ${measured ? `${measured.channels} measured channel row${measured.channels === 1 ? '' : 's'} (${measured.active_channels} active, ${flow(measured.total_flits)} flits)` : 'no loaded measured series'}${packet.scope.run ? ` from ${packet.scope.run.id}` : ''}.`,
      `It cannot answer: ${packet.gaps.join('; ')}.`,
    ],
    evidence: measured ? [
      { label: 'Measured channels', value: String(measured.channels) },
      { label: 'Active', value: String(measured.active_channels) },
      { label: 'Total flits', value: flow(measured.total_flits) },
    ] : [],
    caveats: ['Do not fill these gaps by inference. Unavailable is not zero and not a pass.'],
  };
}

function sectionAnswer(selection: Record<string, unknown>, packet: ContextPacket): LocalAnswer {
  const label = String(selection.label ?? 'Selected region');
  const kind = String(selection.kind ?? 'object');
  const kindLabel: Record<string, string> = {
    section: 'section', chart: 'chart', row: 'table row', cell: 'table cell', metric: 'metric card',
    'utilization-bin': 'utilization bin', element: 'interface element',
  };
  const detail = String(selection.detail ?? '');
  const lines = detail.split('\n');
  const visible = lines.find(line => /^(visible|readable) text:/.test(line))?.replace(/^(visible|readable) text:/, '').trim();
  const extra = lines
    .filter(line => !/^(route|element|visible text|readable text):/.test(line))
    .map(line => line.trim())
    .filter(Boolean)
    .join(' · ');
  const text = visible || extra;
  return {
    paragraphs: [
      `The selected ${kindLabel[kind] ?? kind} is “${label}” on ${packet.scope.page}${packet.scope.run ? `, in ${packet.scope.run.id}` : ''}.`,
      text ? `Attached detail: “${text}”.` : 'Only the object identity is attached; no readable text or measured counter was captured.',
      'This is rendered interface context. Pick a router, channel, wire, endpoint, or endpoint pair when the answer needs measured counters.',
    ],
    evidence: [
      { label: 'Selection', value: label },
      { label: 'Kind', value: kindLabel[kind] ?? kind },
      { label: 'Route', value: packet.scope.route },
    ],
    caveats: ['Rendered text can describe a value without being the measurement itself; use the linked analysis surface before relying on it.'],
  };
}

function contextSummary(packet: ContextPacket): LocalAnswer {
  const selections = packet.selections.map(selection => `${String(selection.kind)} ${String(selection.label ?? selection.id)}`);
  return {
    paragraphs: [
      `Attached context: ${packet.scope.project ? `${packet.scope.project.name} · ` : ''}${packet.scope.page}${packet.scope.run ? ` · ${packet.scope.run.id}` : ''}${selections.length ? ` · ${selections.join('; ')}` : ' · no objects picked'}.`,
      packet.measured
        ? `Measured series: ${packet.measured.channels} channel rows, ${packet.measured.active_channels} active, ${flow(packet.measured.total_flits)} flits.`
        : 'No measured series is loaded for this scope.',
      selections.length ? 'Ask about traffic, queue cost, utilization, latency, or what the evidence does not contain.' : 'Use Pick context and click a router, channel, wire, endpoint, pair, row, metric card, chart mark, or section to attach it.',
    ],
    evidence: [
      ...(packet.scope.run ? [{ label: 'Run', value: packet.scope.run.id }] : []),
      ...(packet.measured ? [{ label: 'Active channels', value: String(packet.measured.active_channels) }] : []),
      { label: 'Selections', value: String(packet.selections.length) },
    ],
    caveats: ['The assistant answers only from the attached context. It does not fetch unselected artifacts or change the draft.'],
  };
}

export function answerLocally(question: string, packet: ContextPacket): LocalAnswer {
  const q = question.trim().toLowerCase();
  if (/(missing|not recorded|not present|gap|limitation)/.test(q)) return missingAnswer(packet);
  const selections = packet.selections;
  const primary = selections.find(selection => ['router', 'channel', 'declared-channel', 'wire', 'endpoint', 'pair'].includes(String(selection.kind))) ?? selections[0];
  if (primary) {
    const kind = String(primary.kind);
    if (kind === 'router') {
      const answer = routerAnswer(primary, q, packet);
      if (answer) return answer;
    }
    if (kind === 'channel' || kind === 'declared-channel') {
      const answer = channelAnswer(primary, q);
      if (answer) return answer;
    }
    if (kind === 'wire') {
      const answer = wireAnswer(primary);
      if (answer) return answer;
    }
    if (kind === 'endpoint') {
      const answer = endpointAnswer(primary);
      if (answer) return answer;
    }
    if (kind === 'pair') {
      const answer = pairAnswer(primary);
      if (answer) return answer;
    }
    return sectionAnswer(primary, packet);
  }
  return contextSummary(packet);
}

export function suggestedQuestions(packet: ContextPacket): string[] {
  const primary = packet.selections.find(selection => ['router', 'channel', 'declared-channel', 'wire', 'endpoint', 'pair'].includes(String(selection.kind)));
  const kind = primary ? String(primary.kind) : '';
  if (kind === 'router') {
    const router = String(primary?.id ?? '');
    return [
      `What traffic leaves R${router}?`,
      `Which channel from R${router} costs the most queue time?`,
      `What is missing from R${router}'s evidence?`,
    ];
  }
  if (kind === 'channel' || kind === 'declared-channel') return [
    `What are CH-${String(primary?.id ?? '')}'s measured counters?`,
    'Is this channel congested?',
    'What is missing from this evidence?',
  ];
  if (kind === 'wire') return ['What does this shared wire connect?', 'How much measured traffic is joined to it?', 'What is missing?'];
  if (kind === 'endpoint') return ['What is this endpoint attached to?', 'What measured traffic reaches its router?', 'What is missing?'];
  if (kind === 'pair') return ['How much traffic is on this pair?', 'What share of the matrix is this?', 'What is missing?'];
  if (packet.selections.length) return ['Summarize this selection', 'What is not shown here?', 'What should I pick next?'];
  return ['What context is attached?', 'What is missing from this evidence?', 'What can you answer?'];
}

export function contextPacketSize(packet: ContextPacket): number {
  return new TextEncoder().encode(JSON.stringify(packet)).length;
}

/** A compact, deterministic sentence used by tests and the drawer footer. */
export function packetSummary(packet: ContextPacket): string {
  const parts = [
    packet.scope.page,
    packet.scope.run?.id ? `run ${packet.scope.run.id}` : 'no run',
    `${packet.selections.length} selection${packet.selections.length === 1 ? '' : 's'}`,
    packet.measured ? `${packet.measured.active_channels} active channels` : 'no measured series',
  ];
  return parts.join(' · ');
}

export function medianQueueCost(packet: ContextPacket): number | null {
  const channels = packet.selections
    .filter(selection => String(selection.kind) === 'router')
    .flatMap(selection => {
      const traffic = selection.resolved as RouterTraffic | undefined;
      return traffic?.top_channels.map(channel => channel.queue_per_flit).filter((value): value is number => value != null) ?? [];
    });
  return median(channels);
}
