import type { AddressWindow, AgentGroup } from './agentMap';
import type { DeclaredAgent, DraftRequest } from './project';
import type { FloorplanView, Topology } from './gateway';
import type { Draft } from './model';
import { DOMAINS, ROUTERS } from './model';

/** Adapters that project the local sample draft onto the documents a loaded
 *  revision supplies, so one renderer serves both modes. Nothing here invents
 *  a measured value: sample coordinates are logical, and undeclared fields stay
 *  undeclared. */

const routerIndex = (router: string) => Math.max(0, ROUTERS.indexOf(router));

/** Agent groups keyed by declared interface identity, in draft order. */
export function localAgentGroups(draft: Draft): AgentGroup[] {
  const groups: AgentGroup[] = [];
  const byKey = new Map<string, number>();
  for (const endpoint of draft.endpoints) {
    const key = `${endpoint.role}|${endpoint.profile}|${endpoint.width}|${endpoint.domain}`;
    const existing = byKey.get(key);
    if (existing !== undefined) { groups[existing].count += 1; continue; }
    byKey.set(key, groups.length);
    groups.push({ kind: endpoint.role, count: 1, data_width: endpoint.width, protocol: endpoint.profile, clock_domain: endpoint.domain, power_domain: null });
  }
  return groups;
}

export function localAgents(draft: Draft): DeclaredAgent[] {
  return localAgentGroups(draft).map(group => ({
    kind: group.kind,
    count: group.count,
    data_width: group.data_width,
    addr_width: undefined,
    protocol: group.protocol,
    clock_domain: group.clock_domain ?? null,
    power_domain: null,
  }));
}

/** The group index an endpoint belongs to, so a seat joins its agent group. */
export function localGroupIndexes(draft: Draft): number[] {
  const byKey = new Map<string, number>();
  return draft.endpoints.map(endpoint => {
    const key = `${endpoint.role}|${endpoint.profile}|${endpoint.width}|${endpoint.domain}`;
    const existing = byKey.get(key);
    if (existing !== undefined) return existing;
    byKey.set(key, byKey.size);
    return byKey.size - 1;
  });
}

/** Declared address regions as address windows; selection policy is undeclared. */
export function localWindows(draft: Draft): AddressWindow[] {
  const groupIndexes = localGroupIndexes(draft);
  return draft.regions.map(region => {
    const endpointIndex = draft.endpoints.findIndex(endpoint => endpoint.id === region.target);
    return {
      id: region.id,
      name: region.id,
      base: BigInt(region.base),
      size: BigInt(region.size),
      targetAgentIdx: endpointIndex >= 0 ? groupIndexes[endpointIndex] : 0,
      selectionPolicy: null,
      targetInstanceIndex: null,
      interleaveBytes: null,
    };
  });
}

/** Region target text, which may name an external integration boundary. */
export function localWindowTargets(draft: Draft): Map<string, string> {
  return new Map(draft.regions.map(region => [region.id, region.target]));
}

export const LOCAL_DIE_UM = 4800;
export const LOCAL_ROUTER_UM = 180;
export const LOCAL_PITCH_UM = 1200;

/** The sample's authored frame and router anchors, in the shape the floorplan
 *  renderer reads. It is declared geometry, not placed geometry. */
export function localFloorplan(): FloorplanView {
  const anchorOffset = LOCAL_PITCH_UM / 2 - LOCAL_ROUTER_UM / 2;
  return {
    contract_version: 1,
    declared: true,
    stale: false,
    revision_id: null,
    topology_hash: null,
    floorplan: {
      die_width_um: LOCAL_DIE_UM,
      die_height_um: LOCAL_DIE_UM,
      routers: ROUTERS.map((_router, index) => ({
        router_id: index,
        x_um: anchorOffset + (index % 4) * LOCAL_PITCH_UM,
        y_um: anchorOffset + Math.floor(index / 4) * LOCAL_PITCH_UM,
        width_um: LOCAL_ROUTER_UM,
        height_um: LOCAL_ROUTER_UM,
      })),
      keepouts: [],
      wire: { ps_per_mm: 120, fixed_ps: 40 },
    },
    derived: null,
  };
}

/** The allowed anchor box is an allowance, not a keepout, so it is drawn as an
 *  annotation instead of being inverted into reserved space. */
export function localPlacementAnnotations(draft: Draft) {
  return [{ id: 'ANCHOR_01', label: 'Allowed anchor window for R_1_2', x_um: Math.max(0, draft.anchor.x - 250), y_um: Math.max(0, draft.anchor.y - 250), width_um: 500, height_um: 500 }];
}

export function localPhysical(): DraftRequest['physical'] {
  const fabricClock = DOMAINS.find(domain => domain.id === 'clk_fabric')?.mhz ?? 1400;
  return { clock_freq_mhz: fabricClock, data_width: 128, num_power_domains: undefined, process_node_nm: undefined };
}

export function localTopology(draft: Draft): Topology {
  const seatCounts = new Map<number, number>();
  for (const endpoint of draft.endpoints) seatCounts.set(routerIndex(endpoint.router), (seatCounts.get(routerIndex(endpoint.router)) ?? 0) + 1);
  const routers = ROUTERS.map((_, index) => ({
    router_id: index,
    coordinates: [index % 4, Math.floor(index / 4)],
    seat_capacity: seatCounts.get(index) ?? 0,
  }));
  const channels: Topology['channels'] = [];
  let channelId = 0;
  const link = (src: number, dst: number) => channels.push({ channel_id: channelId++, src_router: src, dst_router: dst, src_port: 1, dst_port: 1, width_bits: 128, latency_cycles: 1 });
  for (let row = 0; row < 4; row++) {
    for (let column = 0; column < 4; column++) {
      const here = row * 4 + column;
      if (column < 3) { link(here, here + 1); link(here + 1, here); }
      if (row < 3) { link(here, here + 4); link(here + 4, here); }
    }
  }
  const groupIndexes = localGroupIndexes(draft);
  const endpoints = draft.endpoints.map((endpoint, index) => ({
    endpoint_id: index,
    router_id: routerIndex(endpoint.router),
    kind: endpoint.role,
    port_id: endpoint.slot ?? 0,
    group_index: groupIndexes[index],
    instance_index: index,
  }));
  return { family: 'mesh', counts: { routers: routers.length, channels: channels.length, endpoints: endpoints.length, seats: endpoints.length }, routers, channels, endpoints };
}
