/** Graph presets: seed the authoring graph, any edit diverges to custom.
 * Authoring data only — lowering to the compiler lives in adapter.ts. */
import type { GraphEdge, GraphNode, LoomProject } from './project';

export type PresetId =
  | 'mesh-4x4' | 'mesh-8x8' | 'torus-4x4' | 'ring-8' | 'star-8' | 'tree-15' | 'srota-opt-16';

export const PRESETS: { id: PresetId; label: string; hint: string }[] = [
  { id: 'mesh-4x4', label: 'Mesh 4×4', hint: 'mesh' },
  { id: 'mesh-8x8', label: 'Mesh 8×8', hint: '8x8-mesh' },
  { id: 'torus-4x4', label: 'Torus 4×4', hint: 'torus' },
  { id: 'ring-8', label: 'Ring ×8', hint: 'ring' },
  { id: 'star-8', label: 'Star ×8', hint: 'star' },
  { id: 'tree-15', label: 'Tree ×15', hint: 'tree' },
  { id: 'srota-opt-16', label: 'Srota-Opt ×16', hint: 'srota-opt' },
];

const STEP = 120;
let edgeSeq = 0;
const edge = (src: string, dst: string, width = 512): GraphEdge => ({
  id: `e${++edgeSeq}`, src, dst, width, pipelineStages: 1, vcClass: 0,
});
const node = (id: string, x: number, y: number, role = 'compute_tile'): GraphNode => ({
  id, x, y, role, ports: 5, clock: 'clk_core',
});

function gridNodes(cols: number, rows: number, role: (i: number) => string): GraphNode[] {
  return Array.from({ length: cols * rows }, (_, i) => node(
    `n${i + 1}`,
    80 + (i % cols) * STEP,
    80 + Math.floor(i / cols) * STEP,
    role(i),
  ));
}
function meshEdges(cols: number, rows: number): GraphEdge[] {
  const out: GraphEdge[] = [];
  const at = (c: number, r: number): string => `n${r * cols + c + 1}`;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    if (c + 1 < cols) out.push(edge(at(c, r), at(c + 1, r)));
    if (r + 1 < rows) out.push(edge(at(c, r), at(c, r + 1)));
  }
  return out;
}

/** Build a deterministic editable orthogonal mesh within the project size budget. */
export interface MeshPresetOptions {
  endpointIndices?: readonly number[];
  endpointRole?: string;
  nodeRole?: string;
}

export function buildMeshPreset(columns: number, rows: number, options: MeshPresetOptions = {}): LoomProject {
  if (!Number.isSafeInteger(columns) || columns < 1 || !Number.isSafeInteger(rows) || rows < 1) {
    throw new Error('mesh dimensions must be positive integers');
  }
  if (columns * rows > 256) throw new Error('mesh exceeds 256-node project budget');
  const endpointIndices = new Set<number>();
  for (const index of options.endpointIndices ?? []) {
    if (!Number.isSafeInteger(index) || index < 0 || index >= columns * rows) throw new Error(`mesh endpoint index ${index} is outside 0..${columns * rows - 1}`);
    if (endpointIndices.has(index)) throw new Error(`duplicate mesh endpoint index ${index}`);
    endpointIndices.add(index);
  }
  const nodeRole = options.nodeRole ?? 'compute_tile';
  const endpointRole = options.endpointRole ?? 'hbm_controller';
  if (!nodeRole.trim() || !endpointRole.trim()) throw new Error('mesh node and endpoint roles must be non-empty');
  edgeSeq = 0;
  return {
    schemaVersion: 1,
    compilerSemanticsVersion: 1,
    presetHint: 'mesh',
    nodes: gridNodes(columns, rows, (i) => endpointIndices.has(i) ? endpointRole : nodeRole),
    edges: meshEdges(columns, rows),
  };
}

export type RingDirection = 'cw' | 'ccw' | 'bidirectional';

/** Ring with an explicit size and direction. A ring is fully determined by its
 *  size, so a claimed ring is revalidatable from the node count alone. */
export function buildRingPreset(size: number, options: { direction?: RingDirection } = {}): LoomProject {
  if (!Number.isSafeInteger(size) || size < 3 || size > 256) throw new Error('ring size must be an integer in 3..256');
  const direction = options.direction ?? 'cw';
  edgeSeq = 0;
  const nodes = Array.from({ length: size }, (_, i) => node(
    `n${i + 1}`,
    320 + 220 * Math.cos((2 * Math.PI * i) / size),
    260 + 220 * Math.sin((2 * Math.PI * i) / size),
  ));
  const edges: GraphEdge[] = [];
  for (let i = 0; i < size; i++) {
    if (direction === 'cw' || direction === 'bidirectional') edges.push(edge(nodes[i]!.id, nodes[(i + 1) % size]!.id));
    if (direction === 'ccw' || direction === 'bidirectional') edges.push(edge(nodes[i]!.id, nodes[(i - 1 + size) % size]!.id));
  }
  return { schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: 'ring', nodes, edges };
}

/** 2D torus: a mesh with explicit wrap links on both axes (needs ≥3 per axis so
 *  a wrap never duplicates an existing directed link). */
export function buildTorusPreset(columns: number, rows: number): LoomProject {
  if (!Number.isSafeInteger(columns) || columns < 3 || !Number.isSafeInteger(rows) || rows < 3) {
    throw new Error('torus dimensions must be integers ≥ 3');
  }
  if (columns * rows > 256) throw new Error('torus exceeds 256-node project budget');
  const at = (c: number, r: number): string => `n${r * columns + c + 1}`;
  edgeSeq = 0;
  const nodes = gridNodes(columns, rows, () => 'compute_tile');
  const edges = meshEdges(columns, rows);
  for (let r = 0; r < rows; r++) edges.push(edge(at(0, r), at(columns - 1, r)));
  for (let c = 0; c < columns; c++) edges.push(edge(at(c, 0), at(c, rows - 1)));
  return { schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: 'torus', nodes, edges };
}

/** Complete b-ary tree of the given branch factor and depth, in level order. */
export function buildTreePreset(branchFactor: number, depth: number): LoomProject {
  if (!Number.isSafeInteger(branchFactor) || branchFactor < 2) throw new Error('tree branch factor must be an integer ≥ 2');
  if (!Number.isSafeInteger(depth) || depth < 1) throw new Error('tree depth must be a positive integer');
  const total = (branchFactor ** (depth + 1) - 1) / (branchFactor - 1);
  if (total > 256) throw new Error('tree exceeds 256-node project budget');
  edgeSeq = 0;
  const levelRows: number[][] = [];
  let next = 1;
  for (let level = 0; level <= depth; level++) {
    const row: number[] = [];
    for (let k = 0; k < branchFactor ** level; k++) row.push(next++);
    levelRows.push(row);
  }
  const nodes = levelRows.flatMap((row, level) => row.map((n, k) => node(
    `n${n}`,
    120 + k * (960 / row.length),
    80 + level * STEP,
    level === depth ? 'compute_tile' : 'nic',
  )));
  const edges: GraphEdge[] = [];
  for (let level = 0; level < depth; level++) {
    levelRows[level]!.forEach((parent, pIdx) => {
      for (let c = 0; c < branchFactor; c++) {
        const child = levelRows[level + 1]![pIdx * branchFactor + c];
        if (child !== undefined) edges.push(edge(`n${parent}`, `n${child}`));
      }
    });
  }
  return { schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: 'tree', nodes, edges };
}

export type PresetClaim = 'mesh' | 'torus' | 'ring' | 'star' | 'tree' | 'srota-opt' | 'custom';

export interface PresetClaimStatus {
  /** The family the graph actually satisfies, or `custom` when it diverges. */
  claim: PresetClaim;
  /** The declared `presetHint`, unchanged. */
  declared: string | null;
  holds: boolean;
  reason: string;
}

const directedSignature = (project: Pick<LoomProject, 'edges'>): string =>
  project.edges.map((e) => `${e.src}>${e.dst}`).sort().join('|');

function isTreeShape(project: Pick<LoomProject, 'nodes' | 'edges'>): boolean {
  if (project.nodes.length < 2) return false;
  if (project.edges.length !== project.nodes.length - 1) return false;
  const parent = new Map(project.nodes.map((n) => [n.id, n.id]));
  const find = (x: string): string => {
    let root = x;
    while (parent.get(root) !== root) root = parent.get(root)!;
    return root;
  };
  for (const e of project.edges) {
    if (!parent.has(e.src) || !parent.has(e.dst) || e.src === e.dst) return false;
    const a = find(e.src);
    const b = find(e.dst);
    if (a === b) return false;
    parent.set(a, b);
  }
  return true;
}

/** Revalidate a declared preset claim against the current graph (tracker M1-30).
 *  A graph whose `presetHint` no longer matches its structure is reported as
 *  `custom`, so a Mesh/Torus claim can never outlive the topology it named. */
export function presetClaimStatus(project: Pick<LoomProject, 'presetHint' | 'nodes' | 'edges'>): PresetClaimStatus {
  const declared = project.presetHint;
  const diverge = (reason: string): PresetClaimStatus => ({ claim: 'custom', declared, holds: false, reason });
  if (!declared) return diverge('no preset claim: edited or authored directly');
  const whole = Math.round(Math.sqrt(project.nodes.length));
  const square = whole * whole === project.nodes.length ? whole : null;
  const matches = (expected: LoomProject): boolean =>
    expected.nodes.length === project.nodes.length && directedSignature(expected) === directedSignature(project);
  const verdict = (claim: PresetClaim, holds: boolean): PresetClaimStatus => (holds
    ? { claim, declared, holds: true, reason: `matches the declared ${claim} preset` }
    : diverge(`diverges from the declared ${claim} preset`));
  try {
    if (declared === 'mesh' || declared === '8x8-mesh') {
      const side = declared === '8x8-mesh' ? 8 : square;
      if (side === null) return diverge('mesh claim but the node count is not a square grid');
      return verdict('mesh', matches(buildMeshPreset(side, side)));
    }
    if (declared === 'torus') {
      if (square === null || square < 3) return diverge('torus claim but the node count is not a square grid of side ≥ 3');
      return verdict('torus', matches(buildTorusPreset(square, square)));
    }
    if (declared === 'ring') {
      const size = project.nodes.length;
      if (size < 3) return diverge('ring claim but fewer than three nodes');
      const holds = (['cw', 'ccw', 'bidirectional'] as const)
        .some((direction) => matches(buildRingPreset(size, { direction })));
      return verdict('ring', holds);
    }
    if (declared === 'star') return verdict('star', matches(buildPreset('star-8')));
    if (declared === 'tree') return verdict('tree', isTreeShape(project));
    if (declared === 'srota-opt') return verdict('srota-opt', matches(buildPreset('srota-opt-16')));
  } catch {
    return diverge(`the ${declared} claim could not be revalidated`);
  }
  return diverge(`unknown preset claim ${declared}`);
}

export function buildPreset(id: PresetId): LoomProject {
  edgeSeq = 0;
  switch (id) {
    case 'mesh-4x4': {
      const nodes = gridNodes(4, 4, (i) => (i % 5 === 4 ? 'hbm_controller' : 'compute_tile'));
      return { schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: 'mesh', nodes, edges: meshEdges(4, 4) };
    }
    case 'mesh-8x8': {
      const nodes = gridNodes(8, 8, (i) => (i % 9 === 8 ? 'hbm_controller' : 'compute_tile'));
      return { schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: '8x8-mesh', nodes, edges: meshEdges(8, 8) };
    }
    case 'torus-4x4': {
      return buildTorusPreset(4, 4);
    }
    case 'ring-8': {
      return buildRingPreset(8);
    }
    case 'star-8': {
      const hub = { ...node('n1', 320, 260, 'nic'), ports: 7 };
      const nodes = [hub, ...Array.from({ length: 7 }, (_, i) => node(
        `n${i + 2}`,
        320 + 240 * Math.cos((2 * Math.PI * i) / 7),
        260 + 240 * Math.sin((2 * Math.PI * i) / 7),
      ))];
      return { schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: 'star', nodes, edges: nodes.slice(1).map((n) => edge('n1', n.id)) };
    }
    case 'tree-15': {
      return buildTreePreset(2, 3);
    }
    case 'srota-opt-16': {
      // 4×4 with express skip-1 links on rows 1,3 (hint only — compiler
      // lowers this as explicit/mesh until a srota intent kind exists).
      const nodes = gridNodes(4, 4, (i) => (i % 4 === 3 ? 'hbm_controller' : 'compute_tile'));
      const edges = meshEdges(4, 4);
      for (const r of [0, 2]) edges.push(edge(`n${r * 4 + 1}`, `n${r * 4 + 3}`, 1024));
      return { schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: 'srota-opt', nodes, edges };
    }
  }
}
