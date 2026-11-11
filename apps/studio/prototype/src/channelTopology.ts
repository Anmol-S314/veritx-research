import type { Topology } from './gateway';

// BookSim packs a measured output channel as
//   subnet * 100_000_000 + router * 10_000 + output_port
// The output-port index is the router's local port order, not the topology
// artifact's `src_port`. For a 2-D KNCube mesh the fork adds ports as
// E, W, S, N, then the local eject port. Joining the two numbers directly
// silently attributes traffic to the wrong neighbour, so every measured
// channel goes through this module first.
export type Direction = 'east' | 'west' | 'south' | 'north';

export type MeasuredChannelPort = {
  subnet: number;
  router: number;
  port: number;
};

export type ChannelMatch = {
  measured: MeasuredChannelPort;
  local: boolean;
  direction: Direction | null;
  neighbour: number | null;
  channel: Topology['channels'][number] | null;
  unmatched: boolean;
  resourceLabel?: string;
  wire?: { id: number; taps: number[] };
};

export type ChannelIndex = {
  coordinates: Map<number, [number, number]>;
  byCoordinate: Map<string, number>;
  edges: Map<string, Topology['channels'][number][]>;
  grid: boolean;
  wrap: boolean;
  columns: number;
  rows: number;
  srota: boolean;
  concentration: number;
  planes: string[];
  portWires: Map<string, { wire: number; taps: number[] }>;
};

const PORT_DIRECTIONS: Record<number, { direction: Direction; dx: number; dy: number }> = {
  0: { direction: 'east', dx: 1, dy: 0 },
  1: { direction: 'west', dx: -1, dy: 0 },
  2: { direction: 'south', dx: 0, dy: 1 },
  3: { direction: 'north', dx: 0, dy: -1 },
};

const SUBNET_BASE = 100_000_000;
const ROUTER_BASE = 10_000;

/** Decode a packed measured channel id. Invalid ids return null instead of
 *  wrapping into a plausible-looking router or port. */
export function decodeLogicalChannel(packed: number): MeasuredChannelPort | null {
  if (!Number.isFinite(packed) || !Number.isInteger(packed) || packed < 0) return null;
  const subnet = Math.floor(packed / SUBNET_BASE);
  const rest = packed % SUBNET_BASE;
  const router = Math.floor(rest / ROUTER_BASE);
  const port = rest % ROUTER_BASE;
  if (port >= ROUTER_BASE) return null;
  return { subnet, router, port };
}

/** Build the join indexes once per topology. A measured channel is matched by
 *  the neighbour implied by its BookSim port, never by the topology's own
 *  `src_port` numbering (the two are unrelated). */
export function buildChannelIndex(topology: Topology | null, portWires?: Map<string, { wire: number; taps: number[] }>): ChannelIndex {
  const coordinates = new Map<number, [number, number]>();
  for (const router of topology?.routers ?? []) {
    if (Array.isArray(router.coordinates) && router.coordinates.length === 2) {
      const x = Number(router.coordinates[0]), y = Number(router.coordinates[1]);
      if (Number.isFinite(x) && Number.isFinite(y)) coordinates.set(router.router_id, [x, y]);
    }
  }
  const byCoordinate = new Map<string, number>();
  for (const [router, point] of coordinates) byCoordinate.set(`${point[0]}:${point[1]}`, router);
  const edges = new Map<string, Topology['channels'][number][]>();
  for (const channel of topology?.channels ?? []) {
    const key = `${channel.src_router}:${channel.dst_router}`;
    edges.set(key, [...(edges.get(key) ?? []), channel]);
  }
  const family = (topology?.family ?? '').toLowerCase();
  const all2d = (topology?.routers.length ?? 0) > 0 && coordinates.size === topology!.routers.length;
  // KNCube's E/W/S/N/eject port order is only asserted for an ordinary 2-D
  // mesh. A concentrated mesh, a fattree, or a 3-D mesh has a different
  // output-port order; those are left unattributed instead of guessed.
  const grid = all2d && /(^|[-_ ])(mesh|torus|grid|kncube)($|[-_ ])/.test(family) && !/cmesh|concentrat/.test(family);
  const columns = all2d ? Math.max(...[...coordinates.values()].map(point => point[0])) + 1 : 0;
  const rows = all2d ? Math.max(...[...coordinates.values()].map(point => point[1])) + 1 : 0;
  const capacities = new Set((topology?.routers ?? []).map(router => router.seat_capacity));
  const concentration = capacities.size === 1 ? Number([...capacities][0]) : 0;
  return { coordinates, byCoordinate, edges, grid, wrap: /torus/.test(family), columns, rows, srota: family === 'srota', concentration, planes: topology?.planes ?? [], portWires: portWires ?? new Map() };
}

/** Resolve one measured channel to the declared directed link it used, when
 *  the topology makes that unambiguous. Local/eject ports never produce
 *  ingress; an idle boundary port is unmatched but not a network fact. */
export function matchMeasuredChannel(index: ChannelIndex, packed: number): ChannelMatch | null {
  const measured = decodeLogicalChannel(packed);
  if (!measured) return null;
  const base = { measured, local: false, direction: null, neighbour: null, channel: null, unmatched: true };
  // A multi-plane run repeats router/port ids per subnet. This Studio surface
  // is one declared topology, so a non-zero subnet is not joined to it.
  if (index.srota && index.concentration > 0 && index.coordinates.has(measured.router)) {
    const plane = measured.subnet === 0 ? 'Plane D' : measured.subnet === 1 && index.planes.includes('c') ? 'Plane C' : null;
    if (!plane) return base;
    if (measured.port < index.concentration) return { ...base, local: true, unmatched: false, resourceLabel: `${plane} · local terminal ${measured.port}` };
    // BookSim's port index is the driver's own port, not a compass direction and
    // not the topology src_port. Only an executed routing dump can bind it to a
    // wire, because one port carries every tap of exactly one shared wire.
    // The dump is written by the subnet-0 routing function, so it binds Plane D
    // ports only. Plane C has its own port space and must never borrow this map.
    const wire = measured.subnet === 0 ? index.portWires.get(`${measured.router}:${measured.port}`) : undefined;
    if (wire) return { ...base, unmatched: false, wire: { id: wire.wire, taps: wire.taps }, resourceLabel: `${plane} · wire ${wire.wire} driver R${measured.router} → taps ${wire.taps.map(tap => `R${tap}`).join(', ')}` };
    return { ...base, resourceLabel: `${plane} · R${measured.router} port ${measured.port} · ${measured.subnet === 0 ? 'no verified port-to-wire join in this bundle' : 'control-plane port order is not certified in this bundle'}` };
  }
  if (!index.grid || measured.subnet !== 0) return base;
  if (measured.port === 4) return { ...base, local: true, unmatched: false };
  const direction = PORT_DIRECTIONS[measured.port];
  const point = index.coordinates.get(measured.router);
  if (!direction || !point) return base;
  let x = point[0] + direction.dx;
  let y = point[1] + direction.dy;
  if (index.wrap) {
    x = ((x % index.columns) + index.columns) % index.columns;
    y = ((y % index.rows) + index.rows) % index.rows;
  }
  const neighbour = index.byCoordinate.get(`${x}:${y}`) ?? null;
  const candidates = neighbour === null ? [] : index.edges.get(`${measured.router}:${neighbour}`) ?? [];
  // Multiple declared links between the same pair cannot be told apart from
  // the measured id. Leave them unattributed instead of picking one.
  const channel = candidates.length === 1 ? candidates[0] : null;
  return { ...base, direction: direction.direction, neighbour, channel, unmatched: channel === null };
}

export function channelMatchLabel(match: ChannelMatch | null): string {
  if (!match) return 'No measured channel';
  if (match.wire) return `S${match.measured.subnet} · R${match.measured.router} p${match.measured.port} · ${match.resourceLabel}`;
  if (match.resourceLabel) return `S${match.measured.subnet} · R${match.measured.router} p${match.measured.port} · ${match.resourceLabel}`;
  if (match.local) return `R${match.measured.router} p${match.measured.port} · local eject`;
  if (match.channel) return `R${match.measured.router} p${match.measured.port} → R${match.channel.dst_router} p${match.channel.dst_port} · ${match.direction ?? 'declared'}`;
  if (match.direction) return `R${match.measured.router} p${match.measured.port} · ${match.direction} boundary, no declared link`;
  return `R${match.measured.router} p${match.measured.port} · no declared link`;
}
