// Fabric geometry for both canvases. Two sources are never mixed:
//
//   'topology' — the materialized TopologyArtifact + attachments the
//                revision was certified against. Drawn as it is.
//   'intent'   — declared DesignView counts only: a PREVIEW until a
//                compile materializes the graph (router count, agent
//                seats and attachment positions are then unknown).
//
// The canvases render whichever model they are handed and FabricView
// labels the source on screen, so a preview can never impersonate a
// materialized fabric.
import type { DesignView, TopologyView } from './types';

export type FabricSource = 'topology' | 'intent';

export interface FabricNode {
  id: number;
  row: number;
  col: number;
  /** Local attachment seats (topology) or concentration (preview). */
  seats: number;
  /** Attached agents by kind. Empty for a preview: never invented. */
  attached: Record<string, number>;
}

export interface FabricEdge {
  a: number;
  b: number;
  widthBits: number;
}

export interface FabricModel {
  source: FabricSource;
  family: string | null;
  nodes: FabricNode[];
  /** Undirected pairs derived from the directed channel set. */
  edges: FabricEdge[];
  cols: number;
  rows: number;
  concentration: number;
  linkWidth: number | null;
  totals: { compute: number; hbm: number; nic: number; edge: number };
  counts: { routers: number; channels: number; endpoints: number; seats: number };
  topologyHash: string | null;
  revisionId: string | null;
}

/** Agent kinds the canvas draws, grouped into the four legend buckets. */
export function bucketOf(kind: string): 'compute' | 'hbm' | 'nic' | 'edge' {
  switch (kind) {
    case 'compute_tile': return 'compute';
    case 'hbm_controller': return 'hbm';
    case 'nic': return 'nic';
    default: return 'edge';
  }
}

export function agentCount(design: DesignView, kind: string): number {
  return design.agents
    .filter((a) => a.kind === kind)
    .reduce((sum, a) => sum + a.count, 0);
}

export function gridFor(count: number): { cols: number; rows: number } {
  const cols = Math.max(1, Math.ceil(Math.sqrt(Math.max(1, count))));
  const rows = Math.max(1, Math.ceil(Math.max(1, count) / cols));
  return { cols, rows };
}

/** Mesh adjacency over a cols x rows grid (row-major ids). */
function meshEdges(cols: number, rows: number, count: number): [number, number][] {
  const links: [number, number][] = [];
  for (let i = 0; i < count; i++) {
    const c = i % cols;
    const r = Math.floor(i / cols);
    if (c + 1 < cols && i + 1 < count && Math.floor((i + 1) / cols) === r) {
      links.push([i, i + 1]);
    }
    if (r + 1 < rows && i + cols < count) links.push([i, i + cols]);
  }
  return links;
}

function emptyTotals(): { compute: number; hbm: number; nic: number; edge: number } {
  return { compute: 0, hbm: 0, nic: 0, edge: 0 };
}

/** Preview model from declared intent only (no materialized graph yet). */
export function modelFromIntent(design: DesignView): FabricModel {
  const compute = agentCount(design, 'compute_tile');
  const hbm = agentCount(design, 'hbm_controller');
  const nic = agentCount(design, 'nic');
  const edge = nic + agentCount(design, 'peripheral')
    + agentCount(design, 'ucie_port');
  const concentration = design.noc_guided.concentration ?? 1;
  const routerCount = Math.max(1, Math.ceil(compute / Math.max(1, concentration)));
  const { cols, rows } = gridFor(routerCount);

  const nodes: FabricNode[] = [];
  let remaining = compute;
  for (let i = 0; i < routerCount; i++) {
    const seats = Math.min(concentration, Math.max(0, remaining));
    remaining -= seats;
    nodes.push({
      id: i,
      row: Math.floor(i / cols),
      col: i % cols,
      seats: concentration,
      // Attachment POSITIONS are not materialized before a compile, so a
      // preview attaches nothing: the count stays in `totals`.
      attached: {},
    });
  }

  const width = design.noc_guided.link_width;
  const edges: FabricEdge[] = meshEdges(cols, rows, routerCount).map(([a, b]) => ({
    a, b, widthBits: width ?? 64,
  }));

  return {
    source: 'intent',
    family: design.noc_guided.topology_family,
    nodes,
    edges,
    cols,
    rows,
    concentration,
    linkWidth: width ?? null,
    totals: { compute, hbm, nic, edge },
    counts: {
      routers: routerCount,
      channels: edges.length,
      endpoints: 0,
      seats: routerCount * concentration,
    },
    topologyHash: null,
    revisionId: null,
  };
}

/** Model of the certified graph: routers, channels and agent seats. */
export function modelFromTopology(
  topology: TopologyView,
  design: DesignView,
): FabricModel {
  const coords = topology.routers.map((r) => r.coordinates ?? [0]);
  const cols = Math.max(1, ...coords.map((c) => (c[0] ?? 0) + 1));
  const rows = Math.max(
    1,
    ...coords.map((c) => (c.length > 1 ? (c[1] ?? 0) : 0) + 1),
  );

  const attached: Record<number, Record<string, number>> = {};
  const totals = emptyTotals();
  for (const endpoint of topology.endpoints) {
    const bucket = bucketOf(endpoint.kind);
    totals[bucket] += 1;
    const onRouter = attached[endpoint.router_id] ?? {};
    onRouter[endpoint.kind] = (onRouter[endpoint.kind] ?? 0) + 1;
    attached[endpoint.router_id] = onRouter;
  }

  const nodes: FabricNode[] = topology.routers.map((r, index) => ({
    id: r.router_id ?? index,
    row: coords[index].length > 1 ? (coords[index][1] ?? 0) : 0,
    col: coords[index][0] ?? 0,
    seats: r.seat_capacity,
    attached: attached[r.router_id ?? index] ?? {},
  }));

  // Directed channels collapse to undirected physical pairs for drawing;
  // width comes from the channel set (identical per pair by construction).
  const byPair = new Map<string, FabricEdge>();
  for (const channel of topology.channels) {
    const a = Math.min(channel.src_router, channel.dst_router);
    const b = Math.max(channel.src_router, channel.dst_router);
    if (a === b) continue;
    const key = `${a}-${b}`;
    const existing = byPair.get(key);
    if (!existing) {
      byPair.set(key, { a, b, widthBits: channel.width_bits });
    } else {
      existing.widthBits = Math.max(existing.widthBits, channel.width_bits);
    }
  }

  return {
    source: 'topology',
    family: topology.family,
    nodes,
    edges: [...byPair.values()].sort((x, y) => x.a - y.a || x.b - y.b),
    cols,
    rows,
    concentration: design.noc_guided.concentration ?? 1,
    linkWidth: design.noc_guided.link_width ?? topology.channels[0]?.width_bits
      ?? null,
    totals,
    counts: {
      routers: topology.counts.routers,
      channels: topology.counts.channels,
      endpoints: topology.counts.endpoints,
      seats: topology.counts.seats,
    },
    topologyHash: topology.topology_hash,
    revisionId: topology.revision_id,
  };
}

/** Preview or certified graph, whichever the caller has. */
export function fabricModel(
  design: DesignView,
  topology: TopologyView | null | undefined,
): FabricModel {
  return topology ? modelFromTopology(topology, design) : modelFromIntent(design);
}

/** Stroke width for a link (link width in bits → visual weight). */
export function strokeFor(linkWidth: number | null): number {
  if (!linkWidth || linkWidth <= 64) return 1.5;
  if (linkWidth <= 128) return 2.5;
  return 4;
}
