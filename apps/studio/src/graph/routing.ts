/** Canvas Manhattan geometry plus separately tagged authored routing previews.
 * Canvas helpers below remain presentation-only; preview functions are not compiler routes. */
import { supportsXYRouting, type CustomRoutingRule, type LoomProject } from './project';
import type { WorkloadBlock } from './workload';

export interface Pt { x: number; y: number }

export interface ConnectivityHop { edgeId: string; src: string; dst: string; vcClass: number; srcPort?: number; dstPort?: number }
type PortedEdge = { id: string; src: string; dst: string; vcClass: number; srcPort?: number; dstPort?: number };
const routeHop = (edge: PortedEdge, src: string, dst: string): ConnectivityHop => ({
  edgeId: edge.id, src, dst, vcClass: edge.vcClass,
  ...(edge.src === src ? edge.srcPort === undefined ? {} : { srcPort: edge.srcPort } : edge.dstPort === undefined ? {} : { srcPort: edge.dstPort }),
  ...(edge.src === dst ? edge.srcPort === undefined ? {} : { dstPort: edge.srcPort } : edge.dstPort === undefined ? {} : { dstPort: edge.dstPort }),
});
export interface ConnectivityPreview {
  nodePath: string[];
  hops: ConnectivityHop[];
  provenance: 'LOCAL_BFS_CONNECTIVITY_ONLY';
}

export interface XyRoutePreview {
  nodePath: string[];
  hops: ConnectivityHop[];
  policy: 'xy';
  provenance: 'XY_MESH_DIMENSION_ORDER';
}

export interface WestFirstRoutePreview {
  nodePath: string[];
  hops: ConnectivityHop[];
  policy: 'west_first';
  provenance: 'WEST_FIRST_MESH_ORDER';
}

export interface OddEvenRoutePreview {
  nodePath: string[];
  hops: ConnectivityHop[];
  policy: 'odd_even';
  provenance: 'ODD_EVEN_TURN_MODEL_SHORTEST';
}

export interface CustomRoutePreview {
  nodePath: string[];
  hops: ConnectivityHop[];
  policy: 'custom';
  provenance: 'AUTHORED_NEXT_HOP_TABLE';
}

export interface AllowedRouteReachability {
  src: string;
  dst: string;
  perm: 'RO' | 'RW' | 'invalid';
  route: { nodePath: string[]; hops: ConnectivityHop[] } | null;
  error: string | null;
}

/** Audit every explicitly allowed firewall pair; never substitute connectivity
 * BFS for a missing routing policy. */
export function validateAllowedRouteReachability(project: LoomProject): AllowedRouteReachability[] {
  const firewall = project.firewall;
  if (!firewall) return [];
  const rules = firewall.rules;
  if (!Array.isArray(rules)) return [{ src: '*', dst: '*', perm: 'invalid', route: null, error: 'Firewall rules are missing or are not an array.' }];
  const allowedCount = rules.filter((raw) => raw !== null && typeof raw === 'object' && !Array.isArray(raw)
    && ((raw as Record<string, unknown>).perm === 'RO' || (raw as Record<string, unknown>).perm === 'RW')).length;
  const auditBudgetError = allowedCount > 512 ? `Reachability audit refused: ${allowedCount} allowed entries exceed the 512-pair authoring audit budget.` : null;
  return rules.flatMap<AllowedRouteReachability>((raw, index) => {
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
      return [{ src: `rule[${index}]`, dst: '?', perm: 'invalid' as const, route: null, error: `Firewall rule ${index} is not an object.` }];
    }
    const rule = raw as Record<string, unknown>;
    if (rule.perm !== 'RO' && rule.perm !== 'RW') return [];
    if (typeof rule.src !== 'string' || typeof rule.dst !== 'string') {
      return [{ src: typeof rule.src === 'string' ? rule.src : '?', dst: typeof rule.dst === 'string' ? rule.dst : '?', perm: 'invalid' as const, route: null, error: `Allowed firewall rule ${index} has a missing source or destination.` }];
    }
    if (auditBudgetError) return [{ src: rule.src, dst: rule.dst, perm: rule.perm, route: null, error: auditBudgetError }];
    let result: { route: { nodePath: string[]; hops: ConnectivityHop[] } | null; error: string | null };
    switch (project.routing?.policy) {
      case 'xy': result = previewXYPath(project, rule.src, rule.dst); break;
      case 'west_first': result = previewWestFirstPath(project, rule.src, rule.dst); break;
      case 'odd_even': result = previewOddEvenPath(project, rule.src, rule.dst); break;
      case 'custom': result = previewCustomPath(project, rule.src, rule.dst); break;
      default: result = { route: null, error: 'No routing policy is selected for this allowed pair.' };
    }
    return [{ src: rule.src, dst: rule.dst, perm: rule.perm, route: result.route, error: result.error }];
  });
}

export function previewCustomPath(
  project: LoomProject,
  source: string,
  target: string,
): { route: CustomRoutePreview; error: null } | { route: null; error: string } {
  if (project.routing?.policy !== 'custom') return { route: null, error: 'No custom routing policy is selected.' };
  if (!project.nodes.some((node) => node.id === source) || !project.nodes.some((node) => node.id === target)) {
    return { route: null, error: 'Custom route endpoints must be graph nodes.' };
  }
  if (source === target) return { route: { nodePath: [source], hops: [], policy: 'custom', provenance: 'AUTHORED_NEXT_HOP_TABLE' }, error: null };
  const rules = project.routing.rules as CustomRoutingRule[];
  const nextBySource = new Map(rules.filter((rule) => rule.dst === target).map((rule) => [rule.src, rule.nextHop]));
  const edgeByPair = new Map(project.edges.map((edge) => [[edge.src, edge.dst].sort().join('|'), edge]));
  const nodePath = [source];
  const hops: ConnectivityHop[] = [];
  const seen = new Set<string>();
  let current = source;
  while (current !== target) {
    if (seen.has(current)) return { route: null, error: `Custom route loops before reaching ${target} at ${current}.` };
    seen.add(current);
    const next = nextBySource.get(current);
    if (!next) return { route: null, error: `No next-hop rule for ${current} → ${target}.` };
    const edge = edgeByPair.get([current, next].sort().join('|'));
    if (!edge) return { route: null, error: `Next hop ${next} is not adjacent to ${current}.` };
    hops.push(routeHop(edge, current, next));
    current = next;
    nodePath.push(current);
  }
  return { route: { nodePath, hops, policy: 'custom', provenance: 'AUTHORED_NEXT_HOP_TABLE' }, error: null };
}

/** Dimension-order XY route for canonical authored mesh presets only. It uses
 * stable preset node IDs and verified graph adjacency, never canvas x/y. */
export function previewXYPath(
  project: LoomProject,
  source: string,
  target: string,
): { route: XyRoutePreview; error: null } | { route: null; error: string } {
  if (project.routing?.policy !== 'xy') return { route: null, error: 'No XY routing policy is selected.' };
  if (!supportsXYRouting(project)) return { route: null, error: 'XY preview is unsupported for this graph shape; canonical 4×4 or 8×8 mesh adjacency is required.' };
  const side = project.nodes.length === 16 ? 4 : 8;
  const nodeCount = side * side;
  const nodeIndex = (id: string): number | null => {
    const match = /^n([1-9]\d*)$/.exec(id);
    if (!match) return null;
    const index = Number(match[1]) - 1;
    return Number.isSafeInteger(index) && index >= 0 && index < nodeCount ? index : null;
  };
  let current = nodeIndex(source);
  const targetIndex = nodeIndex(target);
  if (current === null || targetIndex === null) return { route: null, error: 'XY endpoints are not canonical mesh router IDs.' };
  const nodePath = [source];
  const hops: ConnectivityHop[] = [];
  const edgeByPair = new Map(project.edges.map((edge) => [[edge.src, edge.dst].sort().join('|'), edge]));
  const targetCol = targetIndex % side;
  const targetRow = Math.floor(targetIndex / side);
  const append = (next: number): boolean => {
    const src = `n${current! + 1}`;
    const dst = `n${next + 1}`;
    const edge = edgeByPair.get([src, dst].sort().join('|'));
    if (!edge) return false;
    hops.push(routeHop(edge, src, dst));
    nodePath.push(dst);
    current = next;
    return true;
  };
  while (current % side !== targetCol) {
    const col = current % side;
    if (!append(current + (targetCol > col ? 1 : -1))) return { route: null, error: 'XY horizontal hop is absent from authored graph.' };
  }
  while (Math.floor(current / side) !== targetRow) {
    const row = Math.floor(current / side);
    if (!append(current + (targetRow > row ? side : -side))) return { route: null, error: 'XY vertical hop is absent from authored graph.' };
  }
  return { route: { nodePath, hops, policy: 'xy', provenance: 'XY_MESH_DIMENSION_ORDER' }, error: null };
}

export function previewWestFirstPath(
  project: LoomProject,
  source: string,
  target: string,
): { route: WestFirstRoutePreview; error: null } | { route: null; error: string } {
  if (project.routing?.policy !== 'west_first') return { route: null, error: 'No West-First routing policy is selected.' };
  if (!supportsXYRouting(project)) return { route: null, error: 'West-First preview is unsupported for this graph shape; canonical 4×4 or 8×8 mesh adjacency is required.' };
  const side = project.nodes.length === 16 ? 4 : 8;
  const indexOf = (id: string): number | null => {
    const match = /^n([1-9]\d*)$/.exec(id);
    const index = match ? Number(match[1]) - 1 : -1;
    return Number.isSafeInteger(index) && index >= 0 && index < side * side ? index : null;
  };
  let current = indexOf(source);
  const destination = indexOf(target);
  if (current === null || destination === null) return { route: null, error: 'West-First endpoints are not canonical mesh router IDs.' };
  const nodePath = [source];
  const hops: ConnectivityHop[] = [];
  const edgeByPair = new Map(project.edges.map((edge) => [[edge.src, edge.dst].sort().join('|'), edge]));
  const targetCol = destination % side;
  const targetRow = Math.floor(destination / side);
  const append = (next: number): boolean => {
    const src = `n${current! + 1}`;
    const dst = `n${next + 1}`;
    const edge = edgeByPair.get([src, dst].sort().join('|'));
    if (!edge) return false;
    hops.push(routeHop(edge, src, dst));
    nodePath.push(dst);
    current = next;
    return true;
  };
  const moveWest = targetCol < current % side;
  const moveHorizontal = (): boolean => {
    while (current! % side !== targetCol) {
      const col = current! % side;
      if (!append(current! + (targetCol > col ? 1 : -1))) return false;
    }
    return true;
  };
  const moveVertical = (): boolean => {
    while (Math.floor(current! / side) !== targetRow) {
      const row = Math.floor(current! / side);
      if (!append(current! + (targetRow > row ? side : -side))) return false;
    }
    return true;
  };
  const ok = moveWest ? moveHorizontal() && moveVertical() : moveVertical() && moveHorizontal();
  if (!ok) return { route: null, error: 'West-First hop is absent from authored graph.' };
  return { route: { nodePath, hops, policy: 'west_first', provenance: 'WEST_FIRST_MESH_ORDER' }, error: null };
}

/** Shortest simple path constrained by the Odd-Even forbidden-turn model on
 * canonical row-major meshes. Logical columns are numbered 1-based from west. */
export function previewOddEvenPath(
  project: LoomProject,
  source: string,
  target: string,
): { route: OddEvenRoutePreview; error: null } | { route: null; error: string } {
  if (project.routing?.policy !== 'odd_even') return { route: null, error: 'No Odd-Even routing policy is selected.' };
  if (!supportsXYRouting(project)) return { route: null, error: 'Odd-Even preview is unsupported for this graph shape; canonical 4×4 or 8×8 mesh adjacency is required.' };
  const side = project.nodes.length === 16 ? 4 : 8;
  const indexOf = (id: string): number | null => {
    const match = /^n([1-9]\d*)$/.exec(id);
    const index = match ? Number(match[1]) - 1 : -1;
    return Number.isSafeInteger(index) && index >= 0 && index < side * side ? index : null;
  };
  const sourceIndex = indexOf(source);
  const targetIndex = indexOf(target);
  if (sourceIndex === null || targetIndex === null) return { route: null, error: 'Odd-Even endpoints are not canonical mesh router IDs.' };
  const nodeIds = Array.from({ length: side * side }, (_, index) => `n${index + 1}`);
  const edgeByPair = new Map(project.edges.map((edge) => [[edge.src, edge.dst].sort().join('|'), edge]));
  if (sourceIndex === targetIndex) return { route: { nodePath: [source], hops: [], policy: 'odd_even', provenance: 'ODD_EVEN_TURN_MODEL_SHORTEST' }, error: null };
  type Direction = 'N' | 'E' | 'S' | 'W';
  type SearchState = { current: number; incoming: Direction | null; path: number[]; visited: Set<number> };
  const queue: SearchState[] = [{ current: sourceIndex, incoming: null, path: [sourceIndex], visited: new Set([sourceIndex]) }];
  const directions: { direction: Direction; delta: number }[] = [
    { direction: 'N', delta: -side }, { direction: 'E', delta: 1 },
    { direction: 'S', delta: side }, { direction: 'W', delta: -1 },
  ];
  let result: number[] | null = null;
  let cursor = 0;
  let expanded = 0;
  while (cursor < queue.length && expanded < 100_000) {
    const state = queue[cursor++]!;
    expanded++;
    const row = Math.floor(state.current / side);
    const col = state.current % side;
    for (const { direction, delta } of directions) {
      if ((direction === 'N' && row === 0) || (direction === 'S' && row === side - 1)
        || (direction === 'W' && col === 0) || (direction === 'E' && col === side - 1)) continue;
      if (state.incoming === 'E' && (direction === 'N' || direction === 'S') && (col + 1) % 2 === 1) continue;
      if ((state.incoming === 'N' || state.incoming === 'S') && direction === 'W' && (col + 1) % 2 === 0) continue;
      const next = state.current + delta;
      if (state.visited.has(next)) continue;
      const nextPath = [...state.path, next];
      if (next === targetIndex) { result = nextPath; queue.length = 0; break; }
      queue.push({ current: next, incoming: direction, path: nextPath, visited: new Set([...state.visited, next]) });
    }
  }
  if (!result) return { route: null, error: 'No Odd-Even-legal simple route was found within the search budget.' };
  const nodePath = result.map((index) => nodeIds[index]!);
  const hops: ConnectivityHop[] = [];
  for (let i = 1; i < nodePath.length; i++) {
    const src = nodePath[i - 1]!;
    const dst = nodePath[i]!;
    const edge = edgeByPair.get([src, dst].sort().join('|'));
    if (!edge) return { route: null, error: `Odd-Even hop ${src} → ${dst} is absent from authored graph.` };
    hops.push(routeHop(edge, src, dst));
  }
  return { route: { nodePath, hops, policy: 'odd_even', provenance: 'ODD_EVEN_TURN_MODEL_SHORTEST' }, error: null };
}

/** Deterministic local connectivity path over authored edges. This does not
 * implement or claim a compiled network route. */
export function previewConnectivityPath(
  nodeIds: readonly string[],
  edges: readonly PortedEdge[],
  source: string,
  target: string,
): ConnectivityPreview | null {
  const nodes = new Set(nodeIds);
  if (!nodes.has(source) || !nodes.has(target)) return null;
  if (source === target) return { nodePath: [source], hops: [], provenance: 'LOCAL_BFS_CONNECTIVITY_ONLY' };
  const adjacency = new Map(nodeIds.map((id) => [id, [] as { node: string; edge: typeof edges[number] }[]]));
  for (const edge of edges) {
    if (!nodes.has(edge.src) || !nodes.has(edge.dst)) continue;
    adjacency.get(edge.src)?.push({ node: edge.dst, edge });
    adjacency.get(edge.dst)?.push({ node: edge.src, edge });
  }
  for (const list of adjacency.values()) list.sort((a, b) => (
    a.edge.id < b.edge.id ? -1 : a.edge.id > b.edge.id ? 1 : a.node < b.node ? -1 : a.node > b.node ? 1 : 0
  ));
  const parent = new Map<string, { node: string; edge: typeof edges[number] }>();
  const seen = new Set([source]);
  const queue = [source];
  for (let index = 0; index < queue.length; index++) {
    const current = queue[index]!;
    for (const next of adjacency.get(current) ?? []) {
      if (seen.has(next.node)) continue;
      seen.add(next.node); parent.set(next.node, { node: current, edge: next.edge });
      if (next.node === target) { queue.length = 0; break; }
      queue.push(next.node);
    }
  }
  if (!parent.has(target)) return null;
  const nodePath = [target];
  const hops: ConnectivityHop[] = [];
  let current = target;
  while (current !== source) {
    const step = parent.get(current)!;
    hops.push(routeHop(step.edge, step.node, current));
    current = step.node; nodePath.push(current);
  }
  return { nodePath: nodePath.reverse(), hops: hops.reverse(), provenance: 'LOCAL_BFS_CONNECTIVITY_ONLY' };
}

/** Local preflight for point-to-point workload VC selection. It verifies the
 * authored mapping against the selected preview route; it is not engine validation. */
export function validateWorkloadRoutingCompatibility(project: LoomProject, workload: WorkloadBlock): string[] {
  const issues: string[] = [];
  for (const [index, operation] of (workload.communications ?? []).entries()) {
    if (operation.kind !== 'point-to-point' || !operation.sourceNodeId || !operation.targetNodeId) continue;
    const mapping = workload.trafficClassMappings?.find((row) => row.trafficClass === operation.trafficClass)
      ?? workload.defaultTrafficClassMapping;
    if (!mapping) continue; // The workload validator owns missing-map errors.
    const pair = `${operation.sourceNodeId} → ${operation.targetNodeId}`;
    if (!project.routing) {
      issues.push(`communications[${index}] (${pair}): no routing policy is selected for traffic-class VC validation`);
      continue;
    }
    const result = project.routing.policy === 'xy' ? previewXYPath(project, operation.sourceNodeId, operation.targetNodeId)
      : project.routing.policy === 'west_first' ? previewWestFirstPath(project, operation.sourceNodeId, operation.targetNodeId)
      : project.routing.policy === 'odd_even' ? previewOddEvenPath(project, operation.sourceNodeId, operation.targetNodeId)
      : previewCustomPath(project, operation.sourceNodeId, operation.targetNodeId);
    if (!result.route) {
      issues.push(`communications[${index}] (${pair}): cannot validate traffic-class VC against route: ${result.error}`);
      continue;
    }
    for (const hop of result.route.hops) if (hop.vcClass !== mapping.vcClass) {
      issues.push(`communications[${index}] (${pair}): traffic class ${operation.trafficClass} maps to VC ${mapping.vcClass}, but edge ${hop.edgeId} uses VC ${hop.vcClass}`);
    }
  }
  return issues;
}

export function manhattan(a: Pt, b: Pt): Pt[] {
  if (a.x === b.x || a.y === b.y) return [a, b];
  const mid: Pt = { x: b.x, y: a.y };
  return [a, mid, b];
}

export interface RouteObstacle { x: number; y: number; width: number; height: number }

/** Route orthogonally around rectangular canvas obstacles. This is a drawing
 * heuristic only; it does not describe a physical route or implementation. */
export function manhattanAvoiding(a: Pt, b: Pt, obstacles: RouteObstacle[], clearance = 8): Pt[] {
  const rects = obstacles.map((rect) => ({
    left: rect.x - clearance, right: rect.x + rect.width + clearance,
    top: rect.y - clearance, bottom: rect.y + rect.height + clearance,
  }));
  const blocked = (p: Pt, q: Pt): boolean => rects.some((r) => {
    if (p.x === q.x) return p.x > r.left && p.x < r.right
      && Math.max(Math.min(p.y, q.y), r.top) < Math.min(Math.max(p.y, q.y), r.bottom);
    if (p.y === q.y) return p.y > r.top && p.y < r.bottom
      && Math.max(Math.min(p.x, q.x), r.left) < Math.min(Math.max(p.x, q.x), r.right);
    return true;
  });
  const simplify = (points: Pt[]): Pt[] => {
    const out: Pt[] = [];
    for (const point of points) {
      if (out.length && out[out.length - 1].x === point.x && out[out.length - 1].y === point.y) continue;
      if (out.length >= 2) {
        const before = out[out.length - 2]; const last = out[out.length - 1];
        if ((before.x === last.x && last.x === point.x) || (before.y === last.y && last.y === point.y)) out.pop();
      }
      out.push(point);
    }
    return out;
  };
  const clear = (points: Pt[]): boolean => points.every((point, index) =>
    index === points.length - 1 || !blocked(point, points[index + 1]));
  const direct = [simplify(manhattan(a, b)), simplify([a, { x: a.x, y: b.y }, b])];
  const directClear = direct.filter(clear);
  if (directClear.length) return directClear[0];

  const xs = new Set<number>(); const ys = new Set<number>();
  for (const rect of rects) { xs.add(rect.left); xs.add(rect.right); ys.add(rect.top); ys.add(rect.bottom); }
  const xCorridors = [...xs].sort((x, y) => Math.min(Math.abs(x - a.x), Math.abs(x - b.x)) - Math.min(Math.abs(y - a.x), Math.abs(y - b.x)));
  const yCorridors = [...ys].sort((y, z) => Math.min(Math.abs(y - a.y), Math.abs(y - b.y)) - Math.min(Math.abs(z - a.y), Math.abs(z - b.y)));
  const candidates: Pt[][] = [];
  for (const x of xCorridors) candidates.push(simplify([a, { x, y: a.y }, { x, y: b.y }, b]));
  for (const y of yCorridors) candidates.push(simplify([a, { x: a.x, y }, { x: b.x, y }, b]));
  candidates.sort((p, q) => manhattanLength(p) - manhattanLength(q));
  return candidates.find(clear) ?? direct[0];
}

/** Manhattan length in canvas units (sums segments). */
export function manhattanLength(pts: Pt[]): number {
  let total = 0;
  for (let i = 1; i < pts.length; i++) {
    total += Math.abs(pts[i].x - pts[i - 1].x) + Math.abs(pts[i].y - pts[i - 1].y);
  }
  return total;
}

/** Crude wire-delay estimate flagged TODO (no PDK): length × k. */
export function wireDelayPs(manhattanUnits: number): number {
  return manhattanUnits * 0.5;
}

export function pathFor(pts: Pt[]): string {
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
}
