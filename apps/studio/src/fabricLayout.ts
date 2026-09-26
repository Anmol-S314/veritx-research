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

/** How a drawn link relates to the declared family. `wrap` is a torus/express
 * wrap-around, `tree` a fat-tree parent→child edge; both are preview-only
 * schematics of a DECLARED structure, never a materialized artifact. */
export type FabricEdgeKind = 'local' | 'wrap' | 'tree';

export interface FabricEdge {
  a: number;
  b: number;
  widthBits: number;
  kind?: FabricEdgeKind;
}

export interface FabricModel {
  source: FabricSource;
  family: string | null;
  /** Preview layout family: a grid mesh or a tiered tree. */
  shape: 'mesh' | 'tree' | 'grid';
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

/** Torus / express wrap-around chords: last↔first in each full row and
 * column. Only the DECLARED family is expressed; the schema is a preview. */
function wrapEdges(cols: number, rows: number, count: number): [number, number][] {
  const links: [number, number][] = [];
  for (let r = 0; r < rows; r++) {
    const first = r * cols;
    const last = Math.min((r + 1) * cols, count) - 1;
    if (last > first) links.push([first, last]);
  }
  for (let c = 0; c < cols; c++) {
    const first = c;
    const last = (rows - 1) * cols + c;
    if (last < count && last > first) links.push([first, last]);
  }
  return links;
}

const TREE_BRANCHING = 4;

/** A tiered k-ary tree schematic for a declared fat tree. Node count is an
 * approximation from declared intent; the materialized tree is backend-owned. */
function treeLayout(count: number): {
  nodes: { row: number; col: number }[];
  edges: [number, number][];
  cols: number;
  rows: number;
} {
  const n = Math.max(1, count);
  const depth: number[] = new Array(n).fill(0);
  const rank: number[] = new Array(n).fill(0);
  const perDepth: number[] = [];
  for (let i = 0; i < n; i++) {
    depth[i] = i === 0 ? 0 : depth[Math.floor((i - 1) / TREE_BRANCHING)] + 1;
    perDepth[depth[i]] = (perDepth[depth[i]] ?? 0) + 1;
    rank[i] = perDepth[depth[i]] - 1;
  }
  const edges: [number, number][] = [];
  for (let i = 1; i < n; i++) {
    edges.push([Math.floor((i - 1) / TREE_BRANCHING), i]);
  }
  return {
    nodes: Array.from({ length: n }, (_, i) => ({ row: depth[i], col: rank[i] })),
    edges,
    cols: Math.max(1, ...perDepth),
    rows: Math.max(1, perDepth.length),
  };
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
  const family = design.noc_guided.topology_family;
  const width = design.noc_guided.link_width;

  // The DECLARED family selects the preview schema. The materialized graph —
  // including its router count and channel set — is backend-owned and only
  // exists after a compile; this is a labelled schematic, never an artifact.
  const isTree = family === 'fat_tree';
  const tree = isTree ? treeLayout(routerCount) : null;
  const cols = tree ? tree.cols : gridFor(routerCount).cols;
  const rows = tree ? tree.rows : gridFor(routerCount).rows;

  const nodes: FabricNode[] = Array.from({ length: routerCount }, (_, i) => ({
    id: i,
    row: tree ? tree.nodes[i].row : Math.floor(i / cols),
    col: tree ? tree.nodes[i].col : i % cols,
    seats: concentration,
    // Attachment POSITIONS are not materialized before a compile, so a
    // preview attaches nothing: the count stays in `totals`.
    attached: {},
  }));

  const edges: FabricEdge[] = tree
    ? tree.edges.map(([a, b]) => ({ a, b, widthBits: width ?? 64, kind: 'tree' }))
    : [
      ...meshEdges(cols, rows, routerCount).map(([a, b]) => (
        { a, b, widthBits: width ?? 64, kind: 'local' as const })),
      ...(family === 'torus' || family === 'gec'
        ? wrapEdges(cols, rows, routerCount).map(([a, b]) => (
          { a, b, widthBits: width ?? 64, kind: 'wrap' as const }))
        : []),
    ];

  return {
    source: 'intent',
    family,
    shape: tree ? 'tree' : 'mesh',
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
/** Drawing hints that a DesignView would otherwise supply.
 *
 * The certified topology carries the drawn graph; concentration and link
 * width are presentation fallbacks. A Compile Result passes them from its
 * own summary group rather than fabricating a DesignView to render a
 * graph it already holds. */
export interface TopologyDrawHints {
  concentration?: number | null;
  linkWidth?: number | null;
}

export function modelFromTopology(
  topology: TopologyView,
  design?: DesignView | null,
  hints?: TopologyDrawHints,
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
    shape: 'grid',
    nodes,
    edges: [...byPair.values()].sort((x, y) => x.a - y.a || x.b - y.b),
    cols,
    rows,
    concentration: design?.noc_guided.concentration
      ?? hints?.concentration ?? 1,
    linkWidth: design?.noc_guided.link_width
      ?? hints?.linkWidth
      ?? topology.channels[0]?.width_bits ?? null,
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

/** The Compile Result path: the frozen certified topology, no DesignView.
 * Concentration and link width come from the compile result's summary. */
export function fabricModelFromTopology(
  topology: TopologyView,
  hints?: TopologyDrawHints,
): FabricModel {
  return modelFromTopology(topology, null, hints);
}

/** Stroke width for a link (link width in bits → visual weight). */
export function strokeFor(linkWidth: number | null): number {
  if (!linkWidth || linkWidth <= 64) return 1.5;
  if (linkWidth <= 128) return 2.5;
  return 4;
}
